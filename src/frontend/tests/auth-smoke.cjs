const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');
(async () => {
 const {createServer}=await import(pathToFileURL(path.join(root, 'node_modules/vite/dist/node/index.js')).href);
 const server=await createServer({root,server:{host:'127.0.0.1',port:0}});
 await server.listen();
 const browser=await chromium.launch({...(process.env.CHROME_BIN ? {executablePath:process.env.CHROME_BIN} : {}),headless:true});
 try {
 const page=await browser.newPage();
 await page.addInitScript(() => {
   window.__authRequests = [];
   const originalFetch = window.fetch;
   window.fetch = (url, options) => {
     if (String(url).startsWith('/api/auth/')) window.__authRequests.push(options.credentials);
     return originalFetch(url, options);
   };
 });
 const errors=[]; page.on('pageerror', e=>errors.push(e.message));
 let user=null, mode='', meCount=0, loginCount=0, lastLogin;
 const demo={id:'user-1',email:'analyst@example.com',role:'Analyst',organizationId:'org-1'};
 await page.route('**/api/auth/**',async route=>{
   const req=route.request(), path=new URL(req.url()).pathname;
   const send=(status,data)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
   if(path.endsWith('/csrf')) return send(200,{csrfToken:'test-csrf-token'});
   if(path.endsWith('/me')) {
     meCount++;
     if(mode==='restore-network') return route.abort();
     if(mode==='null') return send(200,null);
     if(mode==='html') return route.fulfill({status:502,contentType:'text/html',body:'<h1>internal traceback</h1>'});
     return user ? send(200,{user}):send(401,{error:'Authentication required.'});
   }
   if(path.endsWith('/login')) {
     loginCount++; lastLogin=req.postDataJSON();
     if(mode==='login-400') return send(400,{error:'Test validation error.'});
     if(mode==='login-network') return route.abort();
     await new Promise(r=>setTimeout(r,150));
     assert.equal(req.headers()['x-csrf-token'],'test-csrf-token');
     user={...demo,email:lastLogin.email};return send(200,{user});
   }
   if(mode==='logout-fail') return route.abort();
   assert.equal(req.headers()['x-csrf-token'],'test-csrf-token');
   user=null; return route.fulfill({status:204,body:''});
 });
 const url=server.resolvedUrls.local[0];
 const signIn=()=>page.getByRole('button',{name:'Sign In',exact:true});
 const fill=async()=>{await page.locator('input[type=email]').fill('analyst@example.com');await page.locator('input[type=password]').fill('test-value')};
 const loggedIn=()=>page.getByRole('button',{name:/analyst@example.com Analyst/}).waitFor();
 await page.goto(url);await signIn().waitFor();assert.equal(meCount,1);
 await signIn().click();await page.getByText('Email is required.',{exact:true}).waitFor();
 await page.locator('input[type=email]').fill('analyst@example.com');await signIn().click();await page.getByText('Password is required.',{exact:true}).waitFor();assert.equal(loginCount,0);
 await fill();mode='login-400';await signIn().click();await page.getByText('Test validation error.',{exact:true}).waitFor();
 mode='login-network';await signIn().click();await page.getByText('Unable to connect to the authentication service. Please try again.',{exact:true}).waitFor();
 mode='';await page.getByRole('checkbox').check();const before=loginCount;
 await page.locator('input[type=password]').press('Enter');await page.locator('input[type=password]').press('Enter');await loggedIn();assert.equal(loginCount,before+1);assert.equal(lastLogin.rememberMe,true);assert.equal(lastLogin.email,'analyst@example.com');
 assert.ok((await page.evaluate(() => window.__authRequests)).every(value => value === 'include'));
 await page.reload();await loggedIn();assert.equal(meCount,2);
 // Visit discovery without requiring a configured inventory database.
 await page.getByRole('button',{name:'Discover',exact:true}).first().click();
 await page.getByRole('button',{name:'Load snapshot',exact:true}).waitFor();
 await page.getByRole('button',{name:'Display Settings',exact:true}).click();
 await page.getByRole('heading', {name:'Display settings',exact:true}).waitFor();
 // Reload closes appearance panel, and restores session.
 await page.reload();await loggedIn();
 await page.getByRole('button',{name:/analyst@example.com Analyst/}).click();mode='logout-fail';
 await page.getByRole('button',{name:'Sign Out',exact:true}).click();await page.getByRole('alert').waitFor();await loggedIn();
 mode='';await page.getByRole('button',{name:'Sign Out',exact:true}).click();await signIn().waitFor();
 await page.reload();await signIn().waitFor();
 mode='restore-network';await page.reload();await page.getByRole('button',{name:'Retry connection'}).waitFor();
 mode='';await page.getByRole('button',{name:'Retry connection'}).click();await signIn().waitFor();
 for (const bad of ['null','html']) {mode=bad;await page.reload();await page.getByRole('button',{name:'Retry connection'}).waitFor();assert.ok(!(await page.locator('body').innerText()).includes('internal traceback'));}
 assert.deepEqual(errors,[]);
 const storage=await page.evaluate(()=>[JSON.stringify(localStorage),JSON.stringify(sessionStorage)]);
 assert.ok(!storage.join('').includes('test-value'));
 console.log('PASS: Strict Mode single restore, empty fields, API 400, network failure, keyboard submit/repeat protection, remember-me payload, restore, discovery entry, appearance, logout failure/retry, expired session, restore retry, invalid JSON shape/non-JSON fallback.');
 } finally {await browser.close();await server.close();}
})().catch(e=>{console.error(e);process.exit(1)});
