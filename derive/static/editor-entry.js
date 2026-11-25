import {EditorView,basicSetup} from 'codemirror';
import {EditorState,Compartment} from '@codemirror/state';
import {keymap} from '@codemirror/view';
import {indentWithTab} from '@codemirror/commands';
import {indentUnit} from '@codemirror/language';
import {cpp} from '@codemirror/lang-cpp';
import {python} from '@codemirror/lang-python';

export function createEditor(parent,{value='',language='cpp',fontSize=14,tabSize=4,onChange=()=>{},onRun=()=>{}}={}){
 const lang=new Compartment();
 const theme=EditorView.theme({
   '&':{height:'100%',fontSize:fontSize+'px',backgroundColor:'var(--editor-bg)',color:'var(--ink)'},
   '.cm-scroller':{fontFamily:'"SFMono-Regular",Consolas,"Liberation Mono",monospace',lineHeight:'1.65',overflow:'auto'},
   '.cm-content':{padding:'18px 0',caretColor:'var(--primary)'},
   '.cm-line':{padding:'0 20px 0 8px'},
   '.cm-gutters':{backgroundColor:'var(--editor-bg)',color:'var(--subtle)',borderRight:'none',minWidth:'44px'},
   '.cm-gutterElement':{padding:'0 12px'},
   '.cm-activeLine,.cm-activeLineGutter':{backgroundColor:'var(--editor-line)'},
   '&.cm-focused':{outline:'none'},
   '.cm-selectionBackground,&.cm-focused .cm-selectionBackground':{backgroundColor:'var(--selection)'},
   '.cm-cursor':{borderLeftColor:'var(--primary)'},
 });
 const view=new EditorView({parent,state:EditorState.create({doc:value,extensions:[basicSetup,theme,EditorState.tabSize.of(tabSize),indentUnit.of(' '.repeat(tabSize)),lang.of(language==='python'?python():cpp()),keymap.of([{key:'Mod-Enter',run:()=>{onRun();return true;}},indentWithTab]),EditorView.updateListener.of(update=>{if(update.docChanged)onChange(update.state.doc.toString());})]})});
 view.contentDOM.setAttribute('aria-label','Solution code editor');
 return {getValue:()=>view.state.doc.toString(),setValue:value=>view.dispatch({changes:{from:0,to:view.state.doc.length,insert:value}}),setLanguage:language=>view.dispatch({effects:lang.reconfigure(language==='python'?python():cpp())}),focus:()=>view.focus(),destroy:()=>view.destroy(),view};
}
