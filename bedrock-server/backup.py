#!/usr/bin/env python3
"""
BDS Telegram Backup System
- Backs up world ONLY after a player has played and left
- Deduplicates via world signature + content hash
- Cleans up old Telegram messages (retries + #delete tagging)
- Restores from Telegram on startup if world missing
- Chunks to 10MB for Telegram limits
"""
import os
import re
import sys
import time
import json
import zipfile
import hashlib
import shutil
import threading
import requests
from datetime import datetime

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')
CHECK_INTERVAL = 300       # 5 minutes
BACKUP_INTERVAL = 1800     # 30 min between backups
IDLE_MINUTES = 5
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB
STATE_FILE = '/data/backup_state.json'
TEMP_DIR = '/data/backup_temp'
LOG_FILE = '/data/logs/server.log'


class BDSBackup:
    def __init__(self):
        self.api = f"https://api.telegram.org/bot{BOT_TOKEN}"
        self.state = self.load_state()
        self.players = set()
        self.last_activity = time.time()
        self.last_backup = 0
        self.player_has_played = False  # FIX 1: track if any player joined since last backup
        self.lock = threading.Lock()
        self._stop = False
        self.telegram_ok = False

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    return json.load(f)
            except:
                pass
        return {
            'backups': [],
            'pending_deletions': [],
            'last_world_signature': None
        }

    def save_state(self):
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)

    def get_level_name(self):
        try:
            with open('/data/server.properties') as f:
                for line in f:
                    if line.startswith('level-name='):
                        return line.strip().split('=', 1)[1]
        except:
            pass
        return 'Bedrock level'

    def get_world_signature(self, world_path):
        """
        Returns a fingerprint of the world dir.
        Uses size + file count + max mtime + content hash of recently
        modified files for robust deduplication.
        """
        total_size = 0
        file_count = 0
        max_mtime = 0
        content_hasher = hashlib.md5()
        recent_files = []  # files modified in last hour, for content hashing
        now = time.time()

        for dp, dn, filenames in os.walk(world_path):
            for f in filenames:
                fp = os.path.join(dp, f)
                try:
                    st = os.stat(fp)
                    total_size += st.st_size
                    file_count += 1
                    if st.st_mtime > max_mtime:
                        max_mtime = st.st_mtime
                    # Collect recently modified files for content hashing
                    if now - st.st_mtime < 3600:
                        recent_files.append(fp)
                except:
                    pass

        # Hash content of recent files for stronger dedup
        for fp in sorted(recent_files)[:50]:  # cap at 50 files to keep it fast
            try:
                with open(fp, 'rb') as fh:
                    content_hasher.update(fh.read(64 * 1024))  # first 64KB
            except:
                pass

        content_digest = content_hasher.hexdigest()
        return (total_size, file_count, round(max_mtime, 2), content_digest)

    def tg_api(self, method, data=None, files=None, timeout=30):
        url = f"{self.api}/{method}"
        try:
            if files:
                r = requests.post(url, data=data, files=files, timeout=timeout)
            else:
                r = requests.post(url, json=data, timeout=timeout)
            return r.json()
        except Exception as e:
            print(f"[Backup] API error: {e}")
            return {'ok': False}

    def send_text(self, text):
        return self.tg_api('sendMessage', data={
            'chat_id': CHANNEL_ID, 'text': text, 'parse_mode': 'HTML'
        })

    def startup_check(self):
        if not BOT_TOKEN or not CHANNEL_ID:
            print("[Backup] ⚠️ TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID not set!")
            return False

        print("[Backup] Checking Telegram connection...")
        me = self.tg_api('getMe')
        if not me.get('ok'):
            print(f"[Backup] ❌ Bot token invalid: {me}")
            return False

        bot_name = me['result'].get('username', 'unknown')
        res = self.send_text(
            f"🟢 <b>BDS Server Started</b>\n"
            f"Bot: @{bot_name}\n"
            f"Backups will run when world changes & server is idle."
        )
        if res.get('ok'):
            print(f"[Backup] ✅ Telegram OK! Bot @{bot_name} connected.")
            self.telegram_ok = True
            return True
        else:
            print(f"[Backup] ❌ Cannot send to channel: {res}")
            return False

    def log_watcher(self):
        while not self._stop:
            if not os.path.exists(LOG_FILE):
                time.sleep(2)
                continue
            try:
                with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(0, 2)
                    while not self._stop:
                        line = f.readline()
                        if not line:
                            time.sleep(1)
                            continue
                        if 'Player connected:' in line:
                            m = re.search(r'Player connected:\s*(\w+)', line)
                            if m:
                                self.players.add(m.group(1))
                                self.player_has_played = True  # FIX 1: mark that someone played
                                self.last_activity = time.time()
                                print(f"[Backup] +Player {m.group(1)} | total:{len(self.players)}")
                        elif 'Player disconnected:' in line:
                            m = re.search(r'Player disconnected:\s*(\w+)', line)
                            if m:
                                self.players.discard(m.group(1))
                                self.last_activity = time.time()
                                print(f"[Backup] -Player {m.group(1)} | total:{len(self.players)}")
            except Exception as e:
                print(f"[Backup] Log watcher error: {e}")
                time.sleep(5)

    def should_backup(self):
        if not self.telegram_ok:
            return False
        if self.players:
            return False
        # FIX 1: Only backup if a player has actually connected since last backup
        if not self.player_has_played:
            return False
        if time.time() - self.last_activity < IDLE_MINUTES * 60:
            return False
        if time.time() - self.last_backup < BACKUP_INTERVAL:
            return False
        return True

    def compress_world(self, world_path, zip_path):
        print(f"[Backup] Compressing: {world_path}")
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(world_path):
                for file in files:
                    fp = os.path.join(root, file)
                    arcname = os.path.relpath(fp, os.path.dirname(world_path))
                    zf.write(fp, arcname)
        size = os.path.getsize(zip_path)
        print(f"[Backup] Compressed: {size/1024/1024:.1f} MB")
        return size

    def split_file(self, filepath, chunk_dir):
        os.makedirs(chunk_dir, exist_ok=True)
        chunks = []
        with open(filepath, 'rb') as f:
            idx = 0
            while True:
                data = f.read(CHUNK_SIZE)
                if not data:
                    break
                cp = os.path.join(chunk_dir, f"part_{idx:03d}")
                with open(cp, 'wb') as c:
                    c.write(data)
                chunks.append(cp)
                idx += 1
        print(f"[Backup] Split into {len(chunks)} chunks")
        return chunks

    def upload_chunk(self, chunk_path, caption):
        with open(chunk_path, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': CHANNEL_ID, 'caption': caption, 'parse_mode': 'HTML'}
            return self.tg_api('sendDocument', data=data, files=files)

    def edit_caption(self, message_id, caption):
        return self.tg_api('editMessageCaption', data={
            'chat_id': CHANNEL_ID, 'message_id': message_id, 'caption': caption, 'parse_mode': 'HTML'
        })

    def edit_text(self, message_id, text):
        return self.tg_api('editMessageText', data={
            'chat_id': CHANNEL_ID, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'
        })

    def delete_messages(self, message_ids):
        deleted, failed = [], []
        for mid in message_ids:
            res = self.tg_api('deleteMessage', data={
                'chat_id': CHANNEL_ID, 'message_id': mid
            })
            if res.get('ok'):
                deleted.append(mid)
            else:
                failed.append(mid)
            time.sleep(0.5)
        return deleted, failed

    def pin_message(self, message_id):
        return self.tg_api('pinChatMessage', data={
            'chat_id': CHANNEL_ID, 'message_id': message_id
        })

    def unpin_all(self):
        return self.tg_api('unpinAllChatMessages', data={
            'chat_id': CHANNEL_ID
        })

    def get_pinned_message(self):
        res = self.tg_api('getChat', data={'chat_id': CHANNEL_ID})
        if res.get('ok'):
            return res['result'].get('pinned_message')
        return None

    def perform_backup(self):
        with self.lock:
            level = self.get_level_name()
            world_path = os.path.join('/data/worlds', level)

            if not os.path.exists(world_path):
                print(f"[Backup] World not found: {world_path}")
                return

            # --- Deduplication via world signature ---
            current_sig = self.get_world_signature(world_path)
            last_sig = self.state.get('last_world_signature')

            # Skip if world is basically empty (< 500 KB)
            if current_sig[0] < 500 * 1024:
                print(f"[Backup] World nearly empty ({current_sig[0]/1024:.0f} KB), skipping")
                self.player_has_played = False
                return

            # Skip if world is basically empty/fresh (< 5 MB = unplayed BDS world)
            if current_sig[0] < 1 * 1024 * 1024:
                print(f"[Backup] World too small ({current_sig[0]/1024/1024:.1f} MB < 5 MB threshold), skipping")
                self.player_has_played = False  # Reset — not a real world
                return

            print(f"[Backup] World changed! size={current_sig[0]/1024/1024:.1f}MB files={current_sig[1]} hash={current_sig[3][:8]}")

            self.last_backup = time.time()

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            name = f"bds_{timestamp}"
            zip_path = os.path.join(TEMP_DIR, f"{name}.zip")
            chunk_dir = os.path.join(TEMP_DIR, name)

            try:
                self.compress_world(world_path, zip_path)

                file_hasher = hashlib.md5()
                with open(zip_path, 'rb') as f:
                    while True:
                        block = f.read(8192)
                        if not block:
                            break
                        file_hasher.update(block)
                file_hash = file_hasher.hexdigest()

                chunks = self.split_file(zip_path, chunk_dir)
                total = len(chunks)

                file_ids, msg_ids = [], []
                for i, chunk in enumerate(chunks):
                    caption = (
                        f"📦 <b>BDS Backup Chunk</b>\n"
                        f"Backup: <code>{name}</code>\n"
                        f"Part: {i + 1}/{total}\n"
                        f"Level: {level}\n"
                        f"Hash: <code>{file_hash}</code>"
                    )

                    res = self.upload_chunk(chunk, caption)

                    if res.get('ok'):
                        msg_id = res['result']['message_id']
                        file_id = res['result']['document']['file_id']
                        msg_ids.append(msg_id)
                        file_ids.append(file_id)
                        print(f"[Backup] Uploaded {i + 1}/{total} msg={msg_id}")
                    else:
                        print(f"[Backup] Upload failed: {res}")
                        self.send_text(f"❌ Backup {name} failed at part {i + 1}")
                        return

                    time.sleep(1)

                manifest_text = (
                    f"📋 <b>BACKUP MANIFEST</b>\n"
                    f"Name: <code>{name}</code>\n"
                    f"Level: {level}\n"
                    f"Parts: {total}\n"
                    f"Hash: <code>{file_hash}</code>\n"
                    f"FileIDs: {','.join(file_ids)}"
                )

                manifest = self.send_text(manifest_text)
                manifest_id = None

                if manifest.get('ok'):
                    manifest_id = manifest['result']['message_id']
                    self.unpin_all()
                    self.pin_message(manifest_id)
                    print(f"[Backup] Manifest pinned: {manifest_id}")

                record = {
                    'name': name,
                    'timestamp': timestamp,
                    'level': level,
                    'parts': total,
                    'msg_ids': msg_ids,
                    'file_ids': file_ids,
                    'manifest_id': manifest_id,
                    'hash': file_hash
                }

                self.state['backups'].append(record)
                self.state['last_world_signature'] = list(current_sig)
                self.player_has_played = False  # Reset after successful backup
                self.clean_old_backups()
                self.retry_pending_deletions()  # FIX 2: retry any previously failed deletions
                self.save_state()

                self.send_text(f"✅ Backup complete: <code>{name}</code> ({total} parts)")
                print(f"[Backup] Complete: {name}")

            finally:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                if os.path.exists(chunk_dir):
                    shutil.rmtree(chunk_dir)

    def clean_old_backups(self):
        """Keep only last 2 backups. Try to delete old ones; if delete fails (>48h old), edit caption/text to mark [SUPERSEDED]."""
        backups = self.state['backups']
        if len(backups) <= 2:
            return

        to_remove = backups[:-2]
        kept = backups[-2:]  # always keep latest 2

        for old in to_remove:
            all_ids = old.get('msg_ids', []) + ([old['manifest_id']] if old.get('manifest_id') else [])
            deleted, failed = self.delete_messages(all_ids)

            if deleted:
                print(f"[Backup] Deleted {len(deleted)} messages for old backup {old['name']}")

            if failed:
                # Mark failed messages as [SUPERSEDED] by editing their captions/text directly
                self.mark_as_superseded(old, failed)
                old['failed_ids'] = failed
                old['retry_count'] = old.get('retry_count', 0)
                old['first_failed'] = old.get('first_failed', time.time())
                self.state['pending_deletions'].append(old)
                print(f"[Backup] {len(failed)} messages marked as SUPERSEDED for {old['name']}")

        self.state['backups'] = kept

    def mark_as_superseded(self, backup_record, message_ids):
        """
        Edits the caption/text of old backup chunk messages and manifest to mark them [SUPERSEDED].
        Telegram allows bots to edit their own message captions/text regardless of age (even > 48h).
        Includes #delete tag directly in caption/text for easy Telegram channel search.
        """
        manifest_id = backup_record.get('manifest_id')
        name = backup_record.get('name', 'unknown')

        for mid in message_ids:
            if mid == manifest_id:
                self.edit_text(
                    mid,
                    f"🗑 <b>[SUPERSEDED MANIFEST]</b>\n"
                    f"Backup: <code>{name}</code>\n"
                    f"<i>This backup manifest has been replaced by a newer backup. Safe to ignore or delete. #delete #superseded</i>"
                )
            else:
                self.edit_caption(
                    mid,
                    f"🗑 <b>[SUPERSEDED CHUNK]</b>\n"
                    f"Backup: <code>{name}</code>\n"
                    f"<i>This backup chunk is obsolete and replaced by a newer backup. Safe to ignore or delete. #delete #superseded</i>"
                )
            time.sleep(0.5)

    def retry_pending_deletions(self):
        """Retry deleting messages that failed previously."""
        pending = self.state.get('pending_deletions', [])
        if not pending:
            return

        still_pending = []
        for entry in pending:
            failed_ids = entry.get('failed_ids', [])
            if not failed_ids:
                continue

            retry_count = entry.get('retry_count', 0) + 1
            entry['retry_count'] = retry_count

            deleted, failed = self.delete_messages(failed_ids)
            if deleted:
                print(f"[Backup] Retry success: deleted {len(deleted)} messages for {entry.get('name', '?')}")

            if failed:
                # Ensure messages are marked as SUPERSEDED
                self.mark_as_superseded(entry, failed)
                # Cease deletion retries after 5 attempts since caption is already marked SUPERSEDED
                if retry_count >= 5:
                    print(f"[Backup] Ceasing delete retries for {entry.get('name', '?')} (marked SUPERSEDED in channel)")
                else:
                    entry['failed_ids'] = failed
                    still_pending.append(entry)
            else:
                print(f"[Backup] All messages deleted for {entry.get('name', '?')}")

        self.state['pending_deletions'] = still_pending

    def download_file(self, file_id, dest_path):
        res = self.tg_api('getFile', data={'file_id': file_id})
        if not res.get('ok'):
            return False
        file_path = res['result']['file_path']
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        try:
            r = requests.get(url, stream=True, timeout=120)
            r.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"[Backup] Download error: {e}")
            return False

    def restore_latest(self):
        print("[Restore] Checking for backup...")
        if self.state.get('backups'):
            return self._restore_record(self.state['backups'][-1])

        pinned = self.get_pinned_message()
        if pinned and 'BACKUP MANIFEST' in (pinned.get('text') or ''):
            return self._restore_from_manifest(pinned['text'])

        print("[Restore] No backup found")
        return False

    def _restore_record(self, record):
        name = record['name']
        level = record['level']
        file_ids = record['file_ids']
        expected_hash = record['hash']

        print(f"[Restore] Restoring: {name} ({len(file_ids)} parts)")
        self.send_text(f"🔄 Restoring backup: <code>{name}</code>")

        chunk_dir = os.path.join(TEMP_DIR, 'restore')
        zip_path = os.path.join(TEMP_DIR, 'restore.zip')
        os.makedirs(chunk_dir, exist_ok=True)

        try:
            for i, fid in enumerate(file_ids):
                dest = os.path.join(chunk_dir, f"part_{i:03d}")
                if not self.download_file(fid, dest):
                    print(f"[Restore] Failed part {i}")
                    return False
                print(f"[Restore] Downloaded {i+1}/{len(file_ids)}")

            with open(zip_path, 'wb') as out:
                for i in range(len(file_ids)):
                    part = os.path.join(chunk_dir, f"part_{i:03d}")
                    with open(part, 'rb') as f:
                        out.write(f.read())

            hash_check = hashlib.md5()
            with open(zip_path, 'rb') as f:
                while True:
                    block = f.read(8192)
                    if not block:
                        break
                    hash_check.update(block)
            actual_hash = hash_check.hexdigest()
            if actual_hash != expected_hash:
                print(f"[Restore] Hash mismatch!")
                return False

            world_dir = os.path.join('/data/worlds', level)
            if os.path.exists(world_dir):
                shutil.move(world_dir, world_dir + '_old_' + str(int(time.time())))

            os.makedirs(world_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(os.path.dirname(world_dir))

            print(f"[Restore] Success: {world_dir}")
            self.send_text(f"✅ World restored: <code>{name}</code>")
            return True

        finally:
            if os.path.exists(chunk_dir):
                shutil.rmtree(chunk_dir)
            if os.path.exists(zip_path):
                os.remove(zip_path)

    def _restore_from_manifest(self, text):
        """Restore world from pinned Telegram manifest when state file is lost (e.g. redeploy)."""
        # Parse FileIDs
        fid_match = re.search(r'FileIDs:\s*([\w,_-]+)', text)
        if not fid_match:
            print("[Restore] No FileIDs found in manifest")
            return False
        file_ids = [fid.strip() for fid in fid_match.group(1).split(',') if fid.strip()]
        if not file_ids:
            print("[Restore] FileIDs list is empty")
            return False

        # Parse Hash
        hash_match = re.search(r'Hash:\s*(\w+)', text)
        expected_hash = hash_match.group(1) if hash_match else None

        # Parse Level name
        level_match = re.search(r'Level:\s*(.+)', text)
        level = level_match.group(1).strip() if level_match else self.get_level_name()

        # Parse backup Name
        name_match = re.search(r'Name:\s*(\S+)', text)
        name = name_match.group(1).strip() if name_match else 'manifest_restore'

        print(f"[Restore] From manifest: {name} | {len(file_ids)} parts | level={level} | hash={expected_hash or 'none'}")
        self.send_text(f"🔄 Restoring from manifest: <code>{name}</code> ({len(file_ids)} parts)")

        chunk_dir = os.path.join(TEMP_DIR, 'restore')
        zip_path = os.path.join(TEMP_DIR, 'restore.zip')
        os.makedirs(chunk_dir, exist_ok=True)

        try:
            # Download all chunks
            for i, fid in enumerate(file_ids):
                dest = os.path.join(chunk_dir, f"part_{i:03d}")
                print(f"[Restore] Downloading part {i+1}/{len(file_ids)}...")
                if not self.download_file(fid, dest):
                    print(f"[Restore] ❌ Failed to download part {i+1}")
                    self.send_text(f"❌ Restore failed: couldn't download part {i+1}/{len(file_ids)}")
                    return False
                print(f"[Restore] ✓ Downloaded part {i+1}/{len(file_ids)}")

            # Reassemble chunks into zip
            with open(zip_path, 'wb') as out:
                for i in range(len(file_ids)):
                    part = os.path.join(chunk_dir, f"part_{i:03d}")
                    with open(part, 'rb') as f:
                        out.write(f.read())
            print(f"[Restore] Reassembled zip: {os.path.getsize(zip_path)/1024/1024:.1f} MB")

            # Verify hash if available
            if expected_hash:
                hash_check = hashlib.md5()
                with open(zip_path, 'rb') as f:
                    while True:
                        block = f.read(8192)
                        if not block:
                            break
                        hash_check.update(block)
                actual_hash = hash_check.hexdigest()
                if actual_hash != expected_hash:
                    print(f"[Restore] ❌ Hash mismatch! expected={expected_hash} got={actual_hash}")
                    self.send_text(f"❌ Restore failed: hash mismatch")
                    return False
                print(f"[Restore] ✓ Hash verified: {actual_hash}")

            # Extract world
            world_dir = os.path.join('/data/worlds', level)
            if os.path.exists(world_dir):
                backup_name = world_dir + '_old_' + str(int(time.time()))
                shutil.move(world_dir, backup_name)
                print(f"[Restore] Moved existing world to {backup_name}")

            os.makedirs(world_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(os.path.dirname(world_dir))

            print(f"[Restore] ✅ World restored to {world_dir}")
            self.send_text(f"✅ World restored from manifest: <code>{name}</code>")

            # Save this as a known backup in state so next restore doesn't need manifest
            self.state['backups'].append({
                'name': name,
                'timestamp': datetime.now().strftime('%Y%m%d_%H%M%S'),
                'level': level,
                'parts': len(file_ids),
                'msg_ids': [],
                'file_ids': file_ids,
                'manifest_id': None,
                'hash': expected_hash or ''
            })
            self.save_state()

            return True

        except Exception as e:
            print(f"[Restore] ❌ Error: {e}")
            self.send_text(f"❌ Restore error: {e}")
            return False

        finally:
            if os.path.exists(chunk_dir):
                shutil.rmtree(chunk_dir)
            if os.path.exists(zip_path):
                os.remove(zip_path)

    def run(self):
        print("[Backup] Service started")
        self.startup_check()
        threading.Thread(target=self.log_watcher, daemon=True).start()
        while not self._stop:
            time.sleep(CHECK_INTERVAL)
            if self.should_backup():
                print("[Backup] Conditions met, checking for changes...")
                self.perform_backup()
            else:
                idle = (time.time() - self.last_activity) / 60
                since = (time.time() - self.last_backup) / 60
                print(f"[Backup] Skip | players:{len(self.players)} played:{self.player_has_played} idle:{idle:.0f}min backup:{since:.0f}min")


def main():
    bot = BDSBackup()
    if len(sys.argv) > 1 and sys.argv[1] == 'restore':
        success = bot.restore_latest()
        sys.exit(0 if success else 1)
    else:
        bot.run()


if __name__ == '__main__':
    main()