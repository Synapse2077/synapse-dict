"""拿规则G2P跑所有有kaikki IPA的词，比对，报准确率。变位是重点(要补的对象)。"""
import sqlite3, re, random
from b_ipa import word_to_ipa
c=sqlite3.connect("synapse-dict-es.sqlite")

def norm(ipa):
    m=re.search(r"/([^/]+)/", ipa)
    if not m: return None
    s=m.group(1)
    s=s.replace(".","").replace("ˌ","").replace(" ","")
    return s

def run(is_lemma):
    rows=c.execute("SELECT word,phonetic FROM dict WHERE is_lemma=? AND phonetic IS NOT NULL AND word NOT LIKE '% %'",(is_lemma,)).fetchall()
    tot=match=nogen=0; miss=[]
    for w,ph in rows:
        k=norm(ph)
        if not k: continue
        tot+=1
        g=word_to_ipa(w)
        if g is None: nogen+=1; continue
        gn=g.strip("/")
        if gn==k: match+=1
        else: miss.append((w,gn,k))
    return tot,match,nogen,miss

for lem,name in [(0,"变位"),(1,"lemma")]:
    tot,match,nogen,miss=run(lem)
    print(f"{name}: 有真值 {tot}  规则匹配 {match} ({match/tot*100:.2f}%)  未生成 {nogen}")
    random.seed(1); 
    print("  不匹配样本(规则 vs kaikki):")
    for w,g,k in random.sample(miss,min(15,len(miss))):
        print(f"    {w:16} 规则/{g}/  kaikki/{k}/")
    print()
