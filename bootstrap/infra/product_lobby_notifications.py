"""Persistent real-product notifications. Failed delivery never stops workers."""
import json,sqlite3,time,urllib.request
from pathlib import Path
from dotenv import dotenv_values
from product_notice_queue import flush

def main():
    board=Path('/board');source=Path('/source')
    state=json.loads((source/'governance/execution.json').read_text())
    chat=state['telegram_chat_id']
    def send(profile,text):
        token=dotenv_values(source/'profiles'/profile/'.env').get('TELEGRAM_BOT_TOKEN')
        if not token:raise ValueError('missing Telegram credential')
        req=urllib.request.Request('https://api.telegram.org/bot'+token+'/sendMessage',
            data=json.dumps(dict(chat_id=chat,text=text)).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=15) as response:reply=json.load(response)
        if reply.get('ok') is not True:raise RuntimeError('delivery not acknowledged')
    while True:
        if not (board/'lane-events.db').exists():time.sleep(5);continue
        with sqlite3.connect(board/'lane-events.db',timeout=10) as db:
            flush(db,send)
        time.sleep(15)
if __name__=='__main__':main()
