"""Persistent round-robin ordering; retries cannot always occupy the first slot."""
import sqlite3

def ordered(board,cards):
    with sqlite3.connect(board/'lane-events.db',timeout=15) as db:
        db.execute('CREATE TABLE IF NOT EXISTS dispatcher_cursor(id INTEGER PRIMARY KEY CHECK(id=1),task TEXT)')
        row=db.execute('SELECT task FROM dispatcher_cursor WHERE id=1').fetchone()
    keys=list(cards)
    if row and row[0] in keys:
        index=keys.index(row[0])+1;keys=keys[index:]+keys[:index]
    return [(key,cards[key]) for key in keys]

def claimed(board,task):
    with sqlite3.connect(board/'lane-events.db',timeout=15) as db:
        db.execute('INSERT OR REPLACE INTO dispatcher_cursor VALUES(1,?)',(task,))
