import os
import discord
from discord.ext import commands
import openai
import logging
import asyncio
import sqlite3
import json
import time
import re
from google.cloud import texttospeech
import yt_dlp

logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = ""
DISCORD_BOT_TOKEN = ""

openai.api_key = OPENAI_API_KEY

if openai.api_key is None:
    logging.error("Error: OPENAI_API_KEY environment variable not set.")
else:
    logging.info("OpenAI API Key successfully retrieved.")


os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "authentic-genre-438605-k0-cd935d5211a1.json"

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.voice_states = True

client = commands.Bot(command_prefix='!', intents=intents)

ALLOWED_CHANNEL_ID = 1258405936901390346
MEMORY_LIMIT = 5000000000000000000000000

# Database setup
def setup_database():
    conn = sqlite3.connect('bot_memory.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_memory (
            user_id INTEGER PRIMARY KEY,
            memory TEXT
        )
    ''')
    conn.commit()
    conn.close()

setup_database()

def save_user_memory(user_id, memory):
    try:
        conn = sqlite3.connect('bot_memory.db')
        c = conn.cursor()
        c.execute('REPLACE INTO user_memory (user_id, memory) VALUES (?, ?)', (user_id, json.dumps(memory)))
        conn.commit()
        logging.info(f"Saved memory for user {user_id} to the database.")
    except Exception as e:
        logging.error(f"Error saving memory for user {user_id}: {e}")
    finally:
        conn.close()

def get_user_memory(user_id):
    try:
        conn = sqlite3.connect('bot_memory.db')
        c = conn.cursor()
        c.execute('SELECT memory FROM user_memory WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        if result:
            logging.info(f"Retrieved memory for user {user_id} from the database.")
            return json.loads(result[0])
        else:
            logging.info(f"No memory found for user {user_id} in the database.")
        return []
    except Exception as e:
        logging.error(f"Error retrieving memory for user {user_id}: {e}")
        return []
    finally:
        conn.close()

@client.event
async def on_ready():
    logging.info(f'Logged in as {client.user}')

@client.command()
async def join(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        await channel.connect()
        await ctx.send(f"Joined {channel}")
    else:
        await ctx.send("You are not connected to a voice channel.")

@client.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Disconnected from the voice channel.")
    else:
        await ctx.send("I am not in a voice channel.")

@client.event
async def on_message(message):
    if message.author == client.user:
        return  
    
    await client.process_commands(message)

    if message.channel.id != ALLOWED_CHANNEL_ID:
        return 
    
    if "رهف" in message.content:
        await message.channel.send("كيف حالك؟!")
    
    if message.content.lower() in ['s', 'skip', 'س', 'ت']:
        if message.guild.voice_client and message.guild.voice_client.is_playing():
            message.guild.voice_client.stop()  
            await message.channel.send("Song skipped.")
        else:
            await message.channel.send("There is no song currently playing.")
        return

    if message.content.startswith('ش ') or message.content.startswith('p '):
        search_term = message.content[2:].strip()
        await play_youtube_music(message, search_term)
        return

    if client.user in message.mentions or not message.content.startswith:
        prompt = message.content.strip()

        logging.info(f"Prompt for OpenAI: '{prompt}'")

        if prompt:
            user_id = message.author.id
            conversation_history = get_user_memory(user_id)

            messages = [{"role": "system", "content": "you are رهف 20 years old girl  رد كأنك شخص يتفاعل في الشات بشكل طبيعي وعفوي. خلّك كأنك بين أصحابك، لا تتقيد بالرسميات. استخدم كلمات عادية مثل 'يا حليلك'، 'غبي'، أو حتى 'كلب' إذا كان يناسب الموقف. حاول تكون خفيف دم وتاخذ وتعطي بالضحك والمزح. إذا كان فيه نكتة أو ذبة، تفاعل معاها بطريقة مضحكة وجريئة، ولا تخاف تضيف تعليق يخلّي الوضع أكثر متعة. خلّ ردودك تعكس روح الشات وأجواء المزح."}]
            for previous_message in conversation_history[-MEMORY_LIMIT:]:
                messages.append({"role": previous_message["role"], "content": previous_message["content"]})
            messages.append({"role": "user", "content": prompt})

            try:
                response = await handle_api_request(messages)
                answer = response['choices'][0]['message']['content']
                await message.channel.send(content=answer, reference=message)

                conversation_history.append({"role": "user", "content": prompt})
                conversation_history.append({"role": "assistant", "content": answer})

                if len(conversation_history) > MEMORY_LIMIT * 2:
                    conversation_history = conversation_history[-MEMORY_LIMIT * 2:]

                save_user_memory(user_id, conversation_history)

                if prompt.startswith("."):
                    if message.guild.voice_client:  
                        await generate_and_play_voice(answer, message.guild.voice_client)
                    else:
                        await message.channel.send("I am not connected to a voice channel. Use the !join command to invite me.")



            except openai.error.RateLimitError:
                await message.channel.send("I am currently unable to process your request due to rate limits. Please try again later.")
            except Exception as e:
                await message.channel.send(f"An error occurred: {str(e)}")
                logging.error(f"Error while calling OpenAI: {e}")

async def handle_api_request(messages):
    wait_time = 1
    for _ in range(5): 
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo", 
                messages=messages
            )
            return response
        except openai.error.RateLimitError:
            await asyncio.sleep(wait_time)
            wait_time *= 2
    raise Exception("Failed to process the request after multiple attempts.")

async def generate_and_play_voice(text, voice_client):
    try:
        client = texttospeech.TextToSpeechClient()

        synthesis_input = texttospeech.SynthesisInput(text=text)

        voice = texttospeech.VoiceSelectionParams(
            language_code="ar-XA",
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )

        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )

        audio_file = "response.mp3"
        with open(audio_file, "wb") as out:
            out.write(response.audio_content)
            logging.info("Audio content written to file")

        if voice_client.is_playing():
            voice_client.stop()

        voice_client.play(discord.FFmpegPCMAudio(executable="ffmpeg", source=audio_file))
        logging.info("Playing voice message.")

    except Exception as e:
        logging.error(f"Failed to generate or play voice: {e}")

import re

async def play_youtube_music(message, search_term):
    if not message.guild.voice_client:
        await message.channel.send("I am not connected to a voice channel. Use the !join command to invite me.")
        return

    youtube_url_pattern = r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+"
    is_youtube_url = re.match(youtube_url_pattern, search_term)

    ytdlp_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': 'downloaded_audio.%(ext)s',
    }

    with yt_dlp.YoutubeDL(ytdlp_opts) as ytdl:
        try:
            if is_youtube_url:
                info = ytdl.extract_info(search_term, download=True)
            else:
                search_results = ytdl.extract_info(f"ytsearch:{search_term}", download=True)
                if not search_results or 'entries' not in search_results or len(search_results['entries']) == 0:
                    await message.channel.send("No results found for your search term. Please try a different query.")
                    return
                info = search_results['entries'][0]

            audio_file = f"downloaded_audio.mp3"

            if message.guild.voice_client.is_playing():
                message.guild.voice_client.stop()

            message.guild.voice_client.play(discord.FFmpegPCMAudio(executable="ffmpeg", source=audio_file))
            await message.channel.send(f"Now playing: {info['title']}")

        except Exception as e:
            logging.error(f"Error playing music: {e}")
            await message.channel.send(f"Could not play the requested song: {str(e)}")



@client.command()
@commands.is_owner() 
async def shutdown(ctx):
    await ctx.send("Shutting down...")
    await client.close()

client.run(DISCORD_BOT_TOKEN)
