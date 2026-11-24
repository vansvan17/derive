// Snippets run by hand through Claude in Chrome when reading a Codeforces problem.
// They only read the open page (no fetching), and return the text needed to write an entry.

// On a problem page: the statement without samples, and the editorial link.
(()=>{const s=document.querySelector('.problem-statement').cloneNode(true);s.querySelectorAll('script[type^="math/tex"]').forEach(x=>x.replaceWith('$'+x.textContent+'$'));s.querySelectorAll('.MathJax,.MathJax_Preview,.MathJax_Display,.MJX_Assistive_MathML,.sample-tests,.note').forEach(x=>x.remove());const tut=[...document.querySelectorAll('#sidebar a')].filter(a=>/Tutorial|Editorial/i.test(a.textContent)).map(a=>a.href);return 'TUT '+tut.join(' ')+'\n'+s.textContent.replace(/\s+/g,' ').slice(0,2600)})()

// On an editorial page: only the section for problem K + I (e.g. K='2061', I='C').
(()=>{const K='2061',I='C';const c=document.querySelector('.ttypography').cloneNode(true);c.querySelectorAll('script[type^="math/tex"]').forEach(s=>s.replaceWith('$'+s.textContent+'$'));c.querySelectorAll('.MathJax,.MathJax_Preview,.MathJax_Display,.MJX_Assistive_MathML,pre').forEach(x=>x.remove());const t=c.textContent.replace(/[ \t]+\n/g,'\n').replace(/\n{2,}/g,'\n');const re=new RegExp('\\b'+K+'([A-Z]\\d?)\\b','g');let m,s=-1,e=t.length;while((m=re.exec(t))){if(s<0&&m[1]===I)s=m.index;else if(s>=0&&m[1]!==I){e=m.index;break}}return s<0?'NOSECTION '+t.length+' '+t.slice(0,400):t.slice(s,Math.min(e,s+4500))})()
