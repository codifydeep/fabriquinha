"""Persistent eligibility age; bounded priority cannot starve older work."""
def candidates(db,tasks,active,limit,now):
    from product_policy import ROLES
    if type(limit)!=int or limit not in (1,2):raise ValueError('one or two execution slots only')
    db.execute('CREATE TABLE IF NOT EXISTS eligibility(task TEXT PRIMARY KEY,since INTEGER,status TEXT)')
    eligible=[]
    with db:
        ids={t['task'] for t in tasks if t['status'] in ('ready','review') and t['profile'] in ROLES}
        for (tid,) in db.execute('SELECT task FROM eligibility').fetchall():
            if tid not in ids:db.execute('DELETE FROM eligibility WHERE task=?',(tid,))
        for t in tasks:
            if t['task'] not in ids:continue
            prior=db.execute('SELECT since,status FROM eligibility WHERE task=?',(t['task'],)).fetchone()
            if not prior or prior[1]!=t['status']:
                db.execute('INSERT OR REPLACE INTO eligibility VALUES(?,?,?)',(t['task'],now,t['status']));since=now
            else:since=prior[0]
            bonus=600 if t['status']=='review' else 300 if t['scope']=='coordination' else 0
            eligible.append((since-bonus,t['task'],t))
    busy={t['profile'] for t in active};result=[]
    for _,tid,t in sorted(eligible):
        if len(active)+len(result)>=limit:break
        if t['profile'] in busy:continue
        result.append(t);busy.add(t['profile'])
    return result
