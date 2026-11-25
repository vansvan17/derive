import {EditorView,basicSetup} from 'codemirror';
import {EditorState,Compartment} from '@codemirror/state';
import {keymap} from '@codemirror/view';
import {indentWithTab} from '@codemirror/commands';
import {indentUnit,HighlightStyle,syntaxHighlighting} from '@codemirror/language';
import {tags as t} from '@lezer/highlight';

// Code colours come from CSS variables, so they follow the light and dark themes like everything else.
const colours=HighlightStyle.define([
 {tag:[t.keyword,t.modifier,t.controlKeyword,t.operatorKeyword,t.definitionKeyword,t.moduleKeyword],color:'var(--syn-keyword)'},
 {tag:[t.string,t.character,t.special(t.string)],color:'var(--syn-string)'},
 {tag:[t.number,t.bool,t.null,t.atom],color:'var(--syn-number)'},
 {tag:[t.comment,t.lineComment,t.blockComment],color:'var(--syn-comment)',fontStyle:'italic'},
 {tag:[t.typeName,t.className,t.namespace,t.standard(t.typeName)],color:'var(--syn-type)'},
 {tag:[t.function(t.variableName),t.function(t.propertyName),t.definition(t.function(t.variableName))],color:'var(--syn-func)'},
 {tag:[t.meta,t.processingInstruction,t.macroName],color:'var(--syn-meta)'},
 {tag:[t.operator,t.punctuation,t.bracket],color:'var(--syn-punct)'},
 {tag:t.invalid,color:'var(--danger)'},
]);
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
   '.cm-tooltip,.cm-panels':{backgroundColor:'var(--surface)',color:'var(--ink)',border:'1px solid var(--line)'},
   '.cm-tooltip-autocomplete ul li[aria-selected]':{backgroundColor:'var(--primary)',color:'var(--on-primary)'},
   '.cm-matchingBracket,&.cm-focused .cm-matchingBracket':{backgroundColor:'var(--selection)',outline:'none'},
   '.cm-searchMatch':{backgroundColor:'var(--selection)'},
   '.cm-foldPlaceholder':{backgroundColor:'var(--editor-line)',color:'var(--muted)',border:'none'},
   '.cm-textfield,.cm-button':{backgroundColor:'var(--canvas)',color:'var(--ink)',border:'1px solid var(--line)',backgroundImage:'none'},
 });
 const view=new EditorView({parent,state:EditorState.create({doc:value,extensions:[basicSetup,syntaxHighlighting(colours),theme,EditorState.tabSize.of(tabSize),indentUnit.of(' '.repeat(tabSize)),lang.of(language==='python'?python():cpp()),keymap.of([{key:'Mod-Enter',run:()=>{onRun();return true;}},indentWithTab]),EditorView.updateListener.of(update=>{if(update.docChanged)onChange(update.state.doc.toString());})]})});
 view.contentDOM.setAttribute('aria-label','Solution code editor');
 return {getValue:()=>view.state.doc.toString(),setValue:value=>view.dispatch({changes:{from:0,to:view.state.doc.length,insert:value}}),setLanguage:language=>view.dispatch({effects:lang.reconfigure(language==='python'?python():cpp())}),focus:()=>view.focus(),destroy:()=>view.destroy(),view};
}
