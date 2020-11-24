import time
import re
import os
import tempfile
import shutil
import time
import logging
import asyncio
from telnetlib import Telnet

import libtmux
import discord



class DRLoggerManager():
    def __init__(self, bot, credentials, upload_channel_id, log_prefix):
        self.bot = bot
        self.username = credentials['username']
        self.password = credentials['password']
        self.character = credentials['character']
        self.upload_channel_id = upload_channel_id
        self.log_prefix = log_prefix
        self.running = False
        self.startup_lock = asyncio.Lock()


    async def start(self, channel):
        async with self.startup_lock:
            # If this is currently running (recording a log and/or uploading a file)
            # Then tell it to conclude. Wait up to 3 minutes. If it hasn't concluded cleanly, kill it.
            if self.running:
                logging.info('DRLoggerManager is currently recording a log. Attempting to exit cleanly...')

                for i in range(12):
                    if not self.running:
                        break
                    
                    logging.info('DRLoggerManager is awaiting a clean exit...')
                    asyncio.sleep(15)
                    
                if self.running:
                    logging.info('DRLoggerManager could not cleanly exit... Killing with fire...')
                    await self.kill()
            elif libtmux.Server(socket_name='dr-tmux-server'):
                logging.info('Found a lingering TMUX server, maybe from a prior run. Killing it.')
                await self.kill()

            # Runs this in the thread pool because it's a blocking IO task due to telnet connectivity
            loop = asyncio.get_running_loop()
            for i in range(3):
                try:
                    auth_key = await loop.run_in_executor(None, self.authenticate, self.username, self.password, self.character)
                except Exception as e:
                    logger.exception(f'Something went wrong during auth, will try {str(2-i)} more times...')

                if auth_key:
                    break
            
            if not auth_key:
                return await channel.send("😿  💬   Uhoh... Something went wrong, and the scribe didn't wake up...")
            await channel.send("😸  💬   I'll tell the troupe scribe that a meeting is starting!")
            
            log_path = await loop.run_in_executor(None, self.connect_and_run, auth_key)
            logging.info(f'Uploading {log_path} to channel {self.upload_channel_id}...')
            with open(log_path) as f:
                send_file = discord.File(f, filename=f.name, spoiler=False)
                await channel.send("😸  ✉️   Meeting adjourned! Here's the log!", file=send_file)
            logging.info('File upload completed.')


    async def stop(self, channel):
        if self.running:
            await channel.send("😸  💬   I'll tell the troupe scribe that the meeting is over!")
            self.running = False
            logging.info('DRLoggerManager attempting to cleanly stop...')


    def authenticate(self, username, password, character):
        # This implements the EACCESS protocol. I think... Read on if you're into that stuff.
        # https://warlockclient.fandom.com/wiki/EAccess_Protocol
        #
        # This script in particular is a python port of functionality found here:
        # https://github.com/dylb0t/dr-tin/blob/master/bin/drconn.pl
        #
        # Allegedly, this might be deprecated in time. We'll cross that bridge when we get there.
        logging.info('Authenticating and sending login instruction to access.simutronics.com...')
        username = username.encode('ascii')
        password = password.encode('ascii')
        character = character.encode('ascii')

        remote = "access.simutronics.com"
        port = 7900

        auth_key = None
        with Telnet(remote, port) as conn:
            conn.write(b'K\n')
            key = conn.read_until(b'\n', timeout=5).strip()
            newpass = bytearray(len(password))
            for i in range(len(password)):
                c = key[i] ^ password[i]
                c = c ^ 0x40 if key[i] >= ord(b'a') else c
                c = c | 0x80 if c < ord(b' ') else c
                newpass[i] = c
            conn.write(b'A\t' + username + b'\t' + newpass + b'\n')
            key = conn.read_until(b'\n', timeout=5).strip()
            p = re.compile(r'^.+?KEY\t([a-fA-F0-9]+)\t.*$')
            m = p.match(key.decode('ascii'))
            key = m.group(1)

            conn.write(b'G\tDR\n')
            conn.read_until(b'\n', timeout=5).strip()
            conn.write(b'C\n')
            output = conn.read_until(b'\n', timeout=5).strip()
            lines = output.decode('ascii').split('\t')

            pairs = zip(lines[5::2], lines[6::2])
            character_map = {p[0].encode('ascii'): p[1].encode('ascii') for p in pairs}

            found = False
            char_token = None
            for k in character_map:
                if character_map[k].lower() == character.lower():
                    found = True
                    char_token = k
                    break

            if not found:
                return None

            conn.write(b'L\t' + char_token + b'\tPLAY\n')
            conn.read_until(b'\n', timeout=5).strip()
        logging.info('Authentication complete.')
        return key


    def connect_and_run(self, key):
        self.running = True
        
        logging.info('Creating launch file for tintin++...')
        with open('dr.tin', 'w') as tt_file:
            tt_file.write(f'#ses dr prime.dr.game.play.net 4901;{key};;')
            tt_file.write('''
#nop Global Variables
#var \{CURRENT_RT\} \{0\};

#nop Global Roundtime Tracker
#action \{%?Roundtime: %1 sec%+\} \{ #var CURRENT_RT %1; \
#var rtn @roundtime\{\}; #unvar $rtn; \
#delay \{roundtime\} \{#showme <118>Roundtime complete.; \} \{%1\} \}
#action \{%?Roundtime %1 sec%+\} \{ #var CURRENT_RT %1; \
#var rtn @roundtime\{\};#unvar $rtn; \
#delay \{roundtime\} \{#showme <118>Roundtime complete.;\} \{%1\} \}

#read tt/highlight.conf
#read tt/function.conf
#nop #read tt/prompt.conf''')

        logging.info('Creating clean tmux server "dr-tmux-server"... ')
        server = libtmux.Server(socket_name='dr-tmux-server')
        session = server.new_session('dr-window')
        window = session.select_window(0)
        pane = window.select_pane(0)
        logging.info('Starting up DragonRealms via tintin++ client and re-attaching...')

        log_name = f"{self.log_prefix}_{time.strftime('%Y%m%d-%H%M%S')}.txt"
        
        log_path = os.path.join('tt/temp', log_name)
        pane.send_keys('tt++ dr.tin', enter=True)
        time.sleep(15)
        
        pane.send_keys('#config log plain', enter=True)
        pane.send_keys(f'#log overwrite {log_path}', enter=True)
        logging.info(f'tintin++ is now logging to {log_path}')
        
        pane.send_keys('inhale', enter=True)

        seconds_recording = 0
        while self.running:
            # pulse every 3 minutes
            if seconds_recording % 180 == 0:
                pane.send_keys('scrib', enter=True)
            time.sleep(5)
            seconds_recording += 5

        # Upload to discord channel
        channel = discord.utils.get(self.bot.get_all_channels(), id=int(self.upload_channel_id))

        pane.send_keys('nod', enter=True)
        pane.send_keys('wave', enter=True)
        pane.send_keys('exit')

        logging.info('DR Cleanly exited. Killing tmux...')
        server.kill_server()
        self.running = False
        return log_path


    async def kill(self):
        # Ensure that there's no existing server running
        try:
            server = libtmux.Server(socket_name='dr-tmux-server')
            logging.info('Found tmux server, killing...')
            server.kill_server()
            logging.info('Killed tmux server.')
        except:
            pass

        self.running = False


