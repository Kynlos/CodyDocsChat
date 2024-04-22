import asyncio
import webbrowser
import discord
from discord import app_commands
from discord.ui import Select, View
import json
import vertexai
from vertexai.generative_models import GenerativeModel
import vertexai.preview.generative_models as generative_models
import requests
from bs4 import BeautifulSoup
from discord.ui import Button, View
import sqlite3
import re
import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Load the token from config.json
with open('config.json') as f:
    config = json.load(f)
    TOKEN = config['token']
    generation_config = config['generation_config']
    vertexai_config = config['vertexai_config']

intents = discord.Intents.default()
client = discord.Client(intents=intents, heartbeat_timeout=60)
tree = app_commands.CommandTree(client)

conversation_histories = {}



safety_settings = {
    generative_models.HarmCategory.HARM_CATEGORY_HATE_SPEECH: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    generative_models.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    generative_models.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    generative_models.HarmCategory.HARM_CATEGORY_HARASSMENT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
}

def read_text_file(filename):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as file:
            return file.read()
    return ""

def split_into_chunks(text, max_length):
    chunks = []
    current_chunk = ""

    lines = text.splitlines()  # Split on newlines
    for line in lines:
        if len(current_chunk) + len(line) + 1 <= max_length:  # +1 for the newline
            current_chunk += line + "\n"
        else:
            chunks.append(current_chunk.strip())
            current_chunk = line + "\n"

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks
def read_maininfo():
    if os.path.exists("maininfo.md"):
        with open("maininfo.md", 'r', encoding='utf-8') as file:
            return file.read()
    return ""
def generate(user_id, prompt):
    if user_id not in conversation_histories:
        conversation_histories[user_id] = []

    conversation_history = conversation_histories[user_id]

    # Read the content from the text files
    cody_content = "\n".join([read_text_file(f"{command_name}.txt") for command_name in cody_urls.keys()])

    # Read the content from maininfo.md
    maininfo_content = read_maininfo()

    # Concatenate the conversation history with the current prompt, Cody-related content, and maininfo content
    full_prompt = ""
    for user_input, assistant_response in conversation_history:
        full_prompt += f"User: {user_input}\nAssistant: {assistant_response}\n"
    full_prompt += f"User: {prompt}\nCody Documentation:\n{cody_content}\nMain Info:\n{maininfo_content}\nAssistant:"

    vertexai.init(project=vertexai_config['project'], location=vertexai_config['location'])
    model = GenerativeModel(vertexai_config['model'])
    responses = model.generate_content(
        [full_prompt],
        generation_config=generation_config,
        safety_settings=safety_settings,
        stream=True,
    )

    response_text = ""
    try:
        for response in responses:
            response_text += response.text
    except Exception as e:
        print(f"Error during response generation: {str(e)}")
        response_text = "I apologize, but I encountered an error while generating a response. Please try again later."

    # Store the user input and assistant response in the user's conversation history
    conversation_history.append((prompt, response_text))

    # Split the response into chunks at the end of sentences
    response_chunks = split_into_chunks(response_text, max_length=750)

    return response_chunks

def generate_content_chunks(filename):
    content = read_text_file(filename)
    return split_into_chunks(content, max_length=750)

class PaginatedEmbedView(View):
    def __init__(self, response_chunks, user):
        super().__init__(timeout=None)
        self.response_chunks = response_chunks
        self.current_page = 0
        self.user = user

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
    async def previous_page(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            return
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.get_current_embed())

    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def next_page(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            return
        self.current_page = min(len(self.response_chunks) - 1, self.current_page + 1)
        await interaction.response.edit_message(embed=self.get_current_embed())

    def get_current_embed(self):
        embed = discord.Embed(
            title="Cody Docs Chat",
            description=f"{self.response_chunks[self.current_page]}\n\n[Ask on The Forum](https://community.sourcegraph.com)",
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.response_chunks)}")
        embed.set_thumbnail(url="https://sourcegraph.com/docs/logo-theme-dark.svg")
        return embed

class ContentPaginatedEmbedView(View):
    def __init__(self, content_chunks, user):
        super().__init__(timeout=None)
        self.content_chunks = content_chunks
        self.current_page = 0
        self.user = user

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.blurple)
    async def previous_page(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            return
        self.current_page = max(0, self.current_page - 1)
        await interaction.response.edit_message(embed=self.get_current_embed())

    @discord.ui.button(label="Next", style=discord.ButtonStyle.blurple)
    async def next_page(self, interaction: discord.Interaction, button: Button):
        if interaction.user != self.user:
            return
        self.current_page = min(len(self.content_chunks) - 1, self.current_page + 1)
        await interaction.response.edit_message(embed=self.get_current_embed())

    def get_current_embed(self):
        embed = discord.Embed(
            title="Content",
            description=self.content_chunks[self.current_page],
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"Page {self.current_page + 1}/{len(self.content_chunks)}")
        return embed

def store_interaction(prompt, response):
    conn = sqlite3.connect('analytics.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS interactions
                 (prompt TEXT, response TEXT)''')
    c.execute("INSERT INTO interactions VALUES (?, ?)", (prompt, response))
    conn.commit()
    conn.close()

class TextFileHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.src_path.endswith('.txt'):
            file_name = os.path.basename(event.src_path)
            command_name = file_name[:-4]  # Remove the '.txt' extension
            if command_name not in [c.name for c in tree.get_commands()]:
                @tree.command(name=command_name)
                async def content_command(interaction: discord.Interaction, command_name: str = command_name):
                    await interaction.response.defer()
                    content_chunks = generate_content_chunks(f"{command_name}.txt")
                    view = ContentPaginatedEmbedView(content_chunks, interaction.user)
                    await interaction.followup.send(embed=view.get_current_embed(), view=view)
                print(f'New command loaded: {command_name}')
                asyncio.run_coroutine_threadsafe(tree.sync(), client.loop)

class DocsSelectView(View):
    def __init__(self, options):
        super().__init__(timeout=None)
        self.add_item(DocsSelect(options))

class DocsSelect(Select):
    def __init__(self, options):
        super().__init__(placeholder="Select a documentation file", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_file = self.values[0]
        content_chunks = generate_content_chunks(selected_file)
        view = ContentPaginatedEmbedView(content_chunks, interaction.user)
        await interaction.response.send_message(embed=view.get_current_embed(), view=view)

async def reload_commands():
    # Unregister all existing commands
    tree.clear_commands(guild=None)

    # Register new commands based on text files
    for filename in os.listdir():
        if filename.endswith('.txt'):
            command_name = filename[:-4]  # Remove the '.txt' extension
            command_description = f"Get information about {command_name}"

            @tree.command(name=command_name, description=command_description)
            async def command(interaction: discord.Interaction):
                content_chunks = generate_content_chunks(filename)
                view = ContentPaginatedEmbedView(content_chunks, interaction.user)
                await interaction.response.send_message(embed=view.get_current_embed(), view=view)

    # Register hardcoded commands
    tree.add_command(chat)
    tree.add_command(reload)
    tree.add_command(alldocs)
    tree.add_command(resources)

    # Sync the commands once after all registrations
    await tree.sync()

@client.event
async def on_ready():

    # Call the reload_commands() function to register available commands
    await reload_commands()
    await tree.sync()
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('------')
    print('Loaded commands:')
    for command in tree.get_commands():
        print(f'- {command.name}')

    # Start watching for new text files
    observer = Observer()
    observer.schedule(TextFileHandler(), path='.', recursive=False)
    observer.start()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

@tree.command()
@app_commands.describe(prompt='The prompt for the AI')
async def chat(interaction: discord.Interaction, prompt: str):
    await interaction.response.defer()
    user_id = interaction.user.id
    response_chunks = generate(user_id, prompt)

    # Store the interaction in the database
    full_response = "\n".join(response_chunks)
    store_interaction(prompt, full_response)

    view = PaginatedEmbedView(response_chunks, interaction.user)
    await interaction.followup.send(embed=view.get_current_embed(), view=view)

@tree.command()
async def reload(interaction: discord.Interaction):
    authorized_users = [937994994868957184]  # Add more authorized user IDs here

    if interaction.user.id not in authorized_users:
        await interaction.response.send("You are not authorized to use this command.")
        return

    await interaction.response.defer()
    await reload_commands()
    await interaction.followup.send("Commands reloaded successfully.")

@tree.command(name="alldocs", description="Select a documentation file to view")
async def alldocs(interaction: discord.Interaction):
    text_files = [file for file in os.listdir() if file.endswith('.txt')]
    options = []
    for file in text_files:
        command_name = file[:-4]  # Remove the '.txt' extension
        options.append(discord.SelectOption(label=command_name, value=file))

    if not options:
        await interaction.response.send_message("No documentation files found.")
    else:
        view = DocsSelectView(options)
        await interaction.response.send_message("Select a documentation file:", view=view)

@tree.command(name="resources", description="Select a resource to open")
async def resources(interaction: discord.Interaction):
    resource_urls = {
            "Sourcegraph Website": "https://sourcegraph.com",
            "Sourcegraph Cody": "https://sourcegraph.com/cody",
            "Sourcegraph Documentation": "https://docs.sourcegraph.com",
            "Sourcegraph Blog": "https://about.sourcegraph.com/blog",
            "Sourcegraph Support Forum": "https://community.sourcegraph.com/",
            "Sourcegraph Careers": "https://careers.sourcegraph.com",
            "Sourcegraph on GitHub": "https://github.com/sourcegraph",
            "Sourcegraph on Twitter": "https://twitter.com/sourcegraph",
            "Sourcegraph on LinkedIn": "https://www.linkedin.com/company/sourcegraph",
            "Sourcegraph on YouTube": "https://www.youtube.com/c/sourcegraph",
            "Sourcegraph on Spotify": "https://open.spotify.com/user/p3ntuomfda8r7czdbsgy36ogk?si=8095204aefc24587"
    }

    options = []
    for label, url in resource_urls.items():
            options.append(discord.SelectOption(label=label, value=url))
    if not options:
        await interaction.response.send_message("No resources found.")
    else:
            view = ResourceSelectView(options)
            await interaction.response.send_message("Select a resource to open:", view=view)

    # Sync the commands once after all registrations
    await tree.sync()
    
class ResourceSelectView(View):
    def __init__(self, options):
        super().__init__(timeout=None)
        self.add_item(ResourceSelect(options))

class ResourceSelect(Select):
    def __init__(self, options):
        super().__init__(placeholder="Select a resource", options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_url = self.values[0]
        await interaction.response.send_message(f"Click the link to visit the webpage: {selected_url} in your browser...")
        #webbrowser.open(selected_url)
cody_urls = {
    "cody": "https://r.jina.ai/https://sourcegraph.com/docs/cody",
    "quickstart": "https://r.jina.ai/https://sourcegraph.com/docs/cody/quickstart",
    "explanations": "https://r.jina.ai/https://sourcegraph.com/docs/cody/explanations",
    "faq": "https://r.jina.ai/https://sourcegraph.com/docs/cody/faq",
    "capabilities_autocomplete": "https://r.jina.ai/https://sourcegraph.com/docs/cody/capabilities/autocomplete",
    "capabilities_chat": "https://r.jina.ai/https://sourcegraph.com/docs/cody/capabilities/chat",
    "capabilities_commands": "https://r.jina.ai/https://sourcegraph.com/docs/cody/capabilities/commands",
    "capabilities_debug_code": "https://r.jina.ai/https://sourcegraph.com/docs/cody/capabilities/debug-code",
    "capabilities_ignore_context": "https://r.jina.ai/https://sourcegraph.com/docs/cody/capabilities/ignore-context",
    "capabilities_supported_models": "https://r.jina.ai/https://sourcegraph.com/docs/cody/capabilities/supported-models",
    "clients_feature_reference": "https://r.jina.ai/https://sourcegraph.com/docs/cody/clients/feature-reference",
    "core_concepts_context": "https://r.jina.ai/https://sourcegraph.com/docs/cody/core-concepts/context",
    "core_concepts_token_limits": "https://r.jina.ai/https://sourcegraph.com/docs/cody/core-concepts/token-limits",
    "core_concepts_keyword_search": "https://r.jina.ai/https://sourcegraph.com/docs/cody/core-concepts/keyword-search",
    "core_concepts_cody_gateway": "https://r.jina.ai/https://sourcegraph.com/docs/cody/core-concepts/cody-gateway",
    "usage_and_pricing": "https://r.jina.ai/https://sourcegraph.com/docs/cody/usage-and-pricing",
    "troubleshooting": "https://r.jina.ai/https://sourcegraph.com/docs/cody/troubleshooting"
}

client.run(TOKEN)
