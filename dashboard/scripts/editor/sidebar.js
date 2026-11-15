import { setupDocumentMenu } from './document-menu.js';
import { connect, request } from './api.js';
export function setupSidebar() {
  const sidebar=document.querySelector('.blog-sidebar');
  if(!sidebar)return;
  setupDocumentMenu(sidebar);
  const input=sidebar.querySelector('[data-sidebar-search]');
  const results=sidebar.querySelector('[data-sidebar-results]');
  const tree=sidebar.querySelector('[data-sidebar-tree]');
  const message=sidebar.querySelector('[data-sidebar-status]');
  let pages,sequence=0;
  input.addEventListener('input',async()=>{
    const query=input.value.trim().normalize('NFKC').toLocaleLowerCase(); const current=++sequence;
    tree.hidden=Boolean(query);results.hidden=!query;results.replaceChildren();message.textContent='';
    if(!query)return;
    try {
      pages ||= fetch(sidebar.dataset.searchIndex).then(r=>{if(!r.ok)throw new Error();return r.json();});
      const index=await pages;if(current!==sequence)return;
      const found=index.filter(page=>page.section===sidebar.dataset.section&&`${page.title}\n${page.content}`.normalize('NFKC').toLocaleLowerCase().includes(query));
      for(const page of found){const li=document.createElement('li');const a=document.createElement('a');a.href=page.uri;a.textContent=page.title;li.append(a);
        if(page.path&&!/(^|\/)_?index\.md$/.test(page.path)){
          li.className='sidebar-document';li.dataset.documentPath=page.path;li.dataset.documentTitle=page.title;li.dataset.pinned=String(Boolean(page.pinned));
          const more=document.createElement('button');more.type='button';more.className='document-more';more.textContent='⋯';more.setAttribute('aria-label',`${page.title}：更多操作`);more.setAttribute('aria-haspopup','menu');more.setAttribute('aria-expanded','false');li.append(more);
        }
        results.append(li);}
      message.textContent=found.length?`${found.length} result${found.length===1?'':'s'}`:'No matching documents.';
    }catch{pages=null;message.textContent='Search could not be loaded. Try again.';}
  });
  document.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='j'){event.preventDefault();sidebar.querySelector('.blog-navigation-panel').open=true;input.focus();}});
  const menu=sidebar.querySelector('[data-create-menu]');
  const add=sidebar.querySelector('[data-add]');
  add.addEventListener('click',()=>{menu.hidden=!menu.hidden;add.setAttribute('aria-expanded',String(!menu.hidden));if(!menu.hidden)menu.querySelector('button').focus();});
  const hide=()=>{menu.hidden=true;add.setAttribute('aria-expanded','false');};
  document.addEventListener('click',event=>{if(!event.target.closest('.sidebar-create'))hide();});
  sidebar.addEventListener('keydown',event=>{if(event.key==='Escape'){hide();add.focus();}});
  const dialog=document.getElementById('create-entry'); const form=dialog.querySelector('form');
  const parent=dialog.querySelector('[name=parent]'); const title=dialog.querySelector('[name=title]');
  const status=dialog.querySelector('[role=status]'); const submit=dialog.querySelector('[type=submit]');
  let kind,busy=false;
  async function open(type){
    kind=type;hide();dialog.querySelector('h2').textContent=type==='group'?'New group':'New document';form.reset();parent.replaceChildren();status.textContent='Loading groups…';submit.disabled=true;dialog.showModal();
    try{
      const groups=await request(`groups?section=${encodeURIComponent(sidebar.dataset.section)}`);
      for(const group of groups){const option=document.createElement('option');option.value=group.path;option.textContent='— '.repeat(group.depth)+group.title;parent.append(option);}
      if([...parent.options].some(option=>option.value===sidebar.dataset.directory))parent.value=sidebar.dataset.directory;
      status.textContent='';submit.disabled=false;title.focus();
    }catch(error){status.textContent=error.message;}
  }
  menu.querySelectorAll('[data-create-kind]').forEach(button=>button.addEventListener('click',()=>open(button.dataset.createKind)));
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!form.reportValidity())return;busy=true;submit.disabled=true;status.textContent='Creating…';
    try{const result=await request('create',{kind,parent:parent.value,title:title.value});location.assign(result.url+(kind==='document'?'?edit=1':''));}
    catch(error){status.textContent=error.message;busy=false;submit.disabled=false;}
  });
  dialog.querySelector('[data-create-close]').addEventListener('click',()=>{if(!busy){dialog.close();add.focus();}});
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  connect().then(session=>{add.disabled=!session;add.title=session?'Create a document or group':'Run npm run dev to create documents and groups';});
}
