// Snippets run by hand through Claude in Chrome when reading a Codeforces problem.
// They only touch the page already open (no fetching). Each one replaces the page
// body with just the text that is needed, so that reading the page text afterwards
// returns the statement or one editorial section and nothing else. (Returning the
// text from the snippet directly is cut off at about 1000 characters.)

// 1. On a problem page: keep the statement, return the editorial's blog entry number.
(()=>{const s=document.querySelector('.problem-statement');s.querySelectorAll('script[type^=math]').forEach(x=>x.replaceWith('$'+x.textContent+'$'));s.querySelectorAll('.MathJax,.MathJax_Preview,.MathJax_Display,.MJX_Assistive_MathML,.sample-tests,.note,.time-limit,.memory-limit,.input-file,.output-file').forEach(x=>x.remove());const tut=[...document.querySelectorAll('#sidebar a')].filter(a=>/Tutorial|Editorial/i.test(a.textContent)).map(a=>(a.href.match(/entry\/(\d+)/)||[0,'other'])[1]);const art=document.createElement('article');art.textContent=s.textContent.replace(/\s+/g,' ').slice(0,2300);document.body.replaceChildren(art);return 'TUT '+tut.join(' ')})()

// 2. On an editorial page: keep only the section for contest K, problem I
//    (falls back to searching for the title T when the editorial has no problem codes).
(()=>{const K='2061',I='C',T='Kevin and Puzzle';const c=document.querySelector('.ttypography');c.querySelectorAll('script[type^=math]').forEach(s=>s.replaceWith('$'+s.textContent+'$'));c.querySelectorAll('.MathJax,.MathJax_Preview,.MathJax_Display,.MJX_Assistive_MathML,pre,script,style').forEach(x=>x.remove());const t=c.textContent.replace(/\s+/g,' ');const re=/(?<![0-9])([0-9]{4})([A-Z][0-9]?)(?![A-Za-z0-9])/g;let m,s=-1,e=t.length;while((m=re.exec(t))){const hit=m[1]===K&&m[2]===I;if(s<0&&hit)s=m.index;else if(s>=0&&!hit){e=m.index;break}}if(s<0){s=t.indexOf(T);e=s+2600}const art=document.createElement('article');art.textContent=s<0?'NOSECTION '+t.slice(0,1500):t.slice(s,Math.min(e,s+3600));document.body.replaceChildren(art);return s<0?'nosection':'ok'})()
