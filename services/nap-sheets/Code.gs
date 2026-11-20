/* Read-only adapter. Configure Script Properties; do not paste secrets here. */
function doGet(){return HtmlService.createHtmlOutputFromFile('Index').setTitle('D3AD Private NAP Records');}
function same_(a,b){var diff=a.length^b.length;for(var i=0;i<Math.max(a.length,b.length);i++)diff|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return diff===0;}
function authorized_(key){
 if(typeof key!=='string'||key.length<32||key.length>512)throw Error('Access denied');
 var expected=PropertiesService.getScriptProperties().getProperty('NAP_KEY_SHA256')||'';
 var actual=Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,key,Utilities.Charset.UTF_8).map(b=>('0'+((b+256)%256).toString(16)).slice(-2)).join('');
 if(!/^[a-f0-9]{64}$/.test(expected)||!same_(actual,expected))throw Error('Access denied');
}
function getNAPRecords(key){
 authorized_(key); // Verify every read, before accessing the private sheet.
 var id=PropertiesService.getScriptProperties().getProperty('NAP_SHEET_ID');
 if(!id)throw Error('Leadership must configure the sheet connection');
 var ss=SpreadsheetApp.openById(id),nap=ss.getSheetByName('NAP'),contacts=ss.getSheetByName('NAPCont');
 if(!nap||!contacts)throw Error('NAP or NAPCont tab missing');
 if(nap.getLastRow()>10000||contacts.getLastRow()>10000)throw Error('Sheet size needs review');
 var nr=nap.getRange(1,1,Math.max(1,nap.getLastRow()),Math.min(26,nap.getMaxColumns())),cr=contacts.getRange(1,1,Math.max(1,contacts.getLastRow()),Math.min(27,contacts.getMaxColumns()));
 var data=ZRouteNAP.parse(nr.getDisplayValues(),cr.getDisplayValues(),nr.getBackgrounds());
 data.loadedAt=new Date().toISOString();return data;
}
