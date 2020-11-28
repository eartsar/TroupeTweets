import sys
import asyncio
import logging
import shutil
import os
import random
import glob

import discord
import aiofiles


DISCLAIMER_MESSAGE = '''\
ℹ️ BEFORE YOU USE THIS FEATURE, YOU MUST READ THE FOLLOWING DISCLAIMER ℹ️

```Hi trouper. I'm not a lawyer or anything, but I need to be *really clear* 
about a few things before you do this. Also, sorry for constantly popping
this up - I do it whenever the underlying code has changed. So if you're
seeing this - it's because I'm a new, shinier version of myself!

1 - You are uploading a file to a personal server. Don't do this unless 
    you're comfortable with that. This should be obvious, I said it.

2 - While I SHOULD have working functionality to remove photos, I can't
    PROMISE the capability in perpetuity.

3 - You're giving consent for other people in this Discord server - or any
    other Discord server I might be installed on - to potentially view these
    photos through the current implemented features that I support.

4 - I will do my best to be respectful with your data.

4 - You will NOT give me anything even REMOTELY inappropriate. Failure to
    adhere to this can result in me being turned off, or worse.

5 - By clicking the 🆗 emoji below, you understand the risks you're taking
    in using this feature. You recognize that anything that happens after
    submitting data to me is out of your hands. You also recognize that
    I've given my word, and if I fail to uphold my end of the bargain,
    you're within your right to be pissed off and seek revenge.

If you think this disclaimer missed anything that should be made clear, or
if you have any questions or comments about what I do with your data, please
do not hesitate to reach out to Discord user eartsar#3210 - my creator.```'''


def requires_disclaimer(fn):
    from functools import wraps
    @wraps(fn)
    async def wrapper(self, message, *args, **kwargs):
        user_id = message.author.id
        self.sent_command_cache[user_id] = message
        if user_id not in self.accepted_cache:
            pending = None
            for key in self.pending_cache:
                if self.pending_cache[key] == user_id:
                    # send them a reminder to the open message
                    return await message.author.send(f'You have to accept the disclaimer here: {key.jump_url}')
            # send them a disclaimer
            disclaimer_msg = await message.author.send(DISCLAIMER_MESSAGE)
            await disclaimer_msg.add_reaction('🆗')
            await disclaimer_msg.add_reaction('🛑')
            self.pending_cache[disclaimer_msg] = user_id
            return

        # They accepted, all good to go
        return await fn(self, message, *args, **kwargs)
    return wrapper



class PhotosManager():
    def __init__(self, bot, photos_root_path):
        self.bot = bot
        self.photos_root_path = photos_root_path
        self.accepted_cache = set()
        self.pending_cache = {}
        self.sent_command_cache = {}


    async def initialize(self):
        logging.info("Initializing photos manager...")
        # Just log what exists
        return


    async def reaction_handler(self, user, reaction):
        # If this isn't a cached pending disclaimer, skip
        if reaction.message not in self.pending_cache:
            return
        
        # If the reaction is from the owner, and a valid option, interpet it. Otherwise, purge.
        if user.id == self.pending_cache[reaction.message] and reaction.count > 1:
            if reaction.emoji == '🆗':
                del self.pending_cache[reaction.message]
                self.accepted_cache.add(user.id)
                await user.send('👍  You may now use the feature.')
                return await self.bot.on_message(self.sent_command_cache[user.id])
            if reaction.emoji == '🛑':
                del self.pending_cache[reaction.message]
                return await user.send('Please note that accepting the disclaimer is a requirement for using the feature.')
        else:
            await reaction.remove(user)


    @requires_disclaimer
    async def create_album(self, message, album_name):
        album_path = os.path.join(self.photos_root_path, str(message.author.id), album_name.lower())
        os.makedirs(album_path, exist_ok=True)
        return await message.channel.send(f'{message.author.mention} - Created album `{album_name.lower()}`.')


    @requires_disclaimer
    async def delete_album(self, message, album_name):
        album_path = os.path.join(self.photos_root_path, str(message.author.id), album_name)
        if not os.path.exists(album_path):
            return await message.channel.send(f'{message.author.mention} - You don\'t have an album named `{album_name.lower()}`.')
        await asyncio.to_thread(shutil.rmtree, album_path)
        return await message.channel.send(f'{message.author.mention} - Deleted album `{album_name.lower()}`.')


    @requires_disclaimer
    async def wipe_albums(self, message):
        user_path = os.path.join(self.photos_root_path, str(message.author.id))
        if not os.path.exists(user_path):
            return await message.channel.send(f'{message.author.mention} - you don\'t have any albums!')
        await asyncio.to_thread(shutil.rmtree, os.path.join(self.photos_root_path, str(message.author.id)))
        return await message.channel.send(f'{message.author.mention} - Wiped all your albums.')


    @requires_disclaimer
    async def list_albums(self, message):
        user_path = os.path.join(self.photos_root_path, str(message.author.id))
        if not os.path.exists(user_path):
            return await message.channel.send(f'{message.author.mention} - you don\'t have any albums!')
        dirs = sorted([_.lower() for _ in os.listdir(user_path) if os.path.isdir(os.path.join(user_path, _))])
        if not dirs:
            return await message.channel.send(f'{message.author.mention} - you don\'t have any albums!')
        newline = '\n'
        return await message.channel.send(f'{message.author.mention} - you have the following albums:```{newline.join(dirs)}```')


    @requires_disclaimer
    async def fetch(self, message, album_name):
        all_pics = glob.glob(os.path.join(self.photos_root_path, '*', album_name if album_name else '*', '*'))
        random_pic = random.choice(all_pics)
        with open(random_pic, 'rb') as f:
            send_file = discord.File(f, filename=f.name, spoiler=False)
            return await message.channel.send(
                f'Here\'s a random photo{" from album `" + album_name + "`" if album_name else ""}! Who is it...?', file=send_file)


    @requires_disclaimer
    async def upload(self, message, album_name):
        album_path = os.path.join(self.photos_root_path, str(message.author.id), album_name)
        if not os.path.exists(album_path):
            return await message.channel.send(f'{message.author.mention} - You don\'t have an album named `{album_name.lower()}`.')
        elif not message.attachments:
            return await message.channel.send(f'{message.author.mention} - You need to attach either a photo or an archive.')

        attachment = message.attachments[0]
        ext = ('jpg', 'jpeg', 'gif', 'png', 'tiff')
        if not any([attachment.filename.endswith(_) for _ in ext]):
            return await message.channel.send(f'{message.author.mention} - The attached file is not a valid photo or archive.')
        
        if attachment.size > 8388608 and not attachment.filename.endswith('zip'):
            return await message.channel.send(f'{message.author.mention} - Image files must be less than 8 Megabytes')
        
        try:
            await attachment.save(os.path.join(album_path, attachment.filename))
        except Exception:
            return await message.channel.send(f'{message.author.mention} - Something went wrong when downloading the file.')

        return await message.add_reaction('✅')

