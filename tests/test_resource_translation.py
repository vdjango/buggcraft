import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/buggcraft'))
from core.translation import TranslationClient, lookup_items, text_hash
from _qml_test_support import LauncherQmlCase


class TranslationHandler(BaseHTTPRequestHandler):
    calls=[]
    ready=False
    current=True
    body_format='markdown'
    text='这是自动翻译的项目介绍。'

    def log_message(self,*args):
        pass

    def respond(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        type(self).calls.append((self.path,data))
        if self.path.endswith('/sessions/anonymous'):
            return self.respond(dict(access_token='session-test',expires_in=3600))
        if self.path.endswith('/translations:ensure'):
            type(self).ready=True
            return self.respond(dict(results=[]),202)
        results=[]
        for item in data['items']:
            fields=[]
            for field in item['fields']:
                value=dict(field=field['field'],requested_source_hash=field['source_hash'],current_source_hash=field['source_hash'],matches_request=self.ready,state='ready' if self.ready else 'missing')
                value['is_current']=self.current
                value['update']=dict(action='none' if self.current else 'refresh_source',notice='' if self.current else '原文已更新，正在翻译新版本')
                if self.ready:
                    value['translation']=dict(text=self.text,format=self.body_format if field['field']=='body' else 'plain')
                fields.append(value)
            results.append(dict(request_id=item['request_id'],resource=item['resource'],fields=fields))
        self.respond(dict(results=results))


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        TranslationHandler.calls=[];TranslationHandler.ready=False;TranslationHandler.current=True;TranslationHandler.body_format='markdown'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),TranslationHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.url=f'http://127.0.0.1:{self.server.server_port}/v1'
        self.client=TranslationClient(self.temp.name);self.addCleanup(self.client.close)

    def test_automatic_generation_and_persistent_offline_cache(self):
        rows=[dict(source='Modrinth',project_id='fixture1',description='English summary',body='# Original body')]
        first=self.client.resolve(self.url,rows,True)
        self.assertTrue(first['pending'])
        self.assertEqual(sum(p.endswith('translations:ensure') for p,_ in TranslationHandler.calls),1)
        second=self.client.resolve(self.url,rows,True)
        self.assertEqual(second['translations']['0']['body']['text'],TranslationHandler.text)
        calls=len(TranslationHandler.calls)
        self.client.close()
        client=TranslationClient(self.temp.name)
        try:
            cached=client.resolve(self.url,rows,True)
            self.assertFalse(cached['pending'])
            self.assertEqual(cached['translations'],second['translations'])
            self.assertEqual(len(TranslationHandler.calls),calls)
            changed=[dict(rows[0],description='Changed summary')]
            client.resolve(self.url,changed,True)
            self.assertGreater(len(TranslationHandler.calls),calls)
        finally:
            client.close()

    def test_hashes_raw_complete_fields_and_upstream_format(self):
        body='<p>Before\r\nafter</p>'+'x'*25000
        items=lookup_items([dict(source='CurseForge',project_id='123',description='A\r\nB',body=body,body_html=True)],True)
        fields={f['field']:f['source_hash'] for f in items[0]['fields']}
        self.assertEqual(fields['body'],text_hash(body,'body','html'))
        self.assertNotEqual(fields['body'],text_hash(body[:24000],'body','html'))
        self.assertEqual(fields['summary'],text_hash('A\nB','summary'))

    def test_developer_key_is_scoped_to_configured_origin(self):
        with patch.dict(os.environ, {'BUGGCRAFT_TRANSLATION_URL':self.url, 'BUGGCRAFT_TRANSLATION_KEY':'bct_private-test'}):
            self.assertEqual(self.client._auth(self.url), {'Authorization':'Bearer bct_private-test'})
            self.assertFalse(TranslationHandler.calls)
        # A different source must not receive the configured developer key.
        with patch.dict(os.environ, {'BUGGCRAFT_TRANSLATION_URL':'https://other.example/v1', 'BUGGCRAFT_TRANSLATION_KEY':'bct_private-test'}):
            self.assertEqual(self.client._auth(self.url), {'Authorization':'Bearer session-test'})

    def test_failed_submission_does_not_enter_five_minute_cooldown(self):
        from core.translation import TranslationUnavailable
        rows=[dict(source='Modrinth',project_id='fixture1',description='English')]
        original=self.client._request
        def fail_ensure(url, **kwargs):
            if url.endswith('/translations:ensure'):
                raise TranslationUnavailable('Unavailable')
            return original(url, **kwargs)
        with patch.object(self.client, '_request', side_effect=fail_ensure):
            self.assertTrue(self.client.resolve(self.url,rows)['pending'])
        self.assertFalse(self.client.ensured)
        self.client.resolve(self.url,rows)
        self.assertEqual(sum(p.endswith('translations:ensure') for p,_ in TranslationHandler.calls),1)

    def test_html_translation_and_outdated_revision_notice(self):
        rows=[dict(source='CurseForge',project_id='123',description='English',body='<p>Original</p>',body_html=True)]
        TranslationHandler.ready=True
        TranslationHandler.body_format='html'
        result=self.client.resolve(self.url,rows,True)
        self.assertEqual(result['translations']['0']['body']['format'],'html')
        # A new source hash bypasses the local cache. Historical artifacts must
        # not be silently displayed as the latest translation.
        TranslationHandler.current=False
        changed=[dict(rows[0],description='Updated English',body='<p>Updated</p>')]
        result=self.client.resolve(self.url,changed,True)
        self.assertFalse(result['translations'])
        self.assertIn('原文已更新',result['status'])


class TranslationQmlTests(LauncherQmlCase):
    def test_setting_switch_autotranslates_and_restores_original(self):
        controller=self.window.download_page.content_page.controller
        from ui.pages.qml_settings import SettingsController
        settings=SettingsController(self.window,'general')
        self.assertFalse(self.manager.get_setting('translation.enabled'))
        source=next(f for f in settings.fields if f['key']=='translation.source')
        self.assertFalse(source['enabled'])
        settings.setValue('translation.enabled',True)
        self.assertTrue(self.manager.get_setting('translation.enabled'))
        self.assertTrue(next(f for f in settings.fields if f['key']=='translation.source')['enabled'])
        response=dict(translations={'0':{'summary':dict(text='自动中文简介',format='plain'),'body':dict(text='自动中文正文',format='markdown')}},pending=False,status='',retry=2)
        with patch.object(controller.translation_client,'resolve',return_value=response) as mock:
            controller.results=[dict(source='Modrinth',project_id='fixture',title='Project',description='Original summary')]
            controller.view='browse';controller._translation_tick()
            self.wait_until(lambda:controller.results[0].get('translated_summary')=='自动中文简介')
            self.assertEqual(controller.results[0]['description'],'Original summary')
            self.assertEqual(controller.results[0]['display_summary'],'自动中文简介')
            self.assertTrue(mock.called)
            controller.request_id+=1
            controller.view='detail';controller.selected_project=dict(controller.results[0],body='Original body',body_text='Original body')
            controller._translation_tick()
            self.wait_until(lambda:controller.selected_project.get('translated_body')=='自动中文正文')
            self.assertFalse(controller.show_original)
            controller.toggleOriginal();self.assertTrue(controller.show_original)
            settings.setValue('translation.enabled',False)
            controller._translation_tick()
            self.assertEqual(controller.results[0]['display_summary'],'Original summary')
            self.assertFalse(controller.selected_project.get('translated_body'))
        controller.translation_pool.waitForDone(3000)
        self.assert_no_qml_errors()

    def test_late_translation_never_overwrites_new_search(self):
        controller=self.window.download_page.content_page.controller
        self.manager.set_setting('translation.enabled',True)
        controller.results=[dict(source='Modrinth',project_id='old',description='Old')]
        controller.view='browse';controller.translation_enabled=True
        signature=(True,'https://translate.bugg.icu/v1',controller.request_id,'browse',(('Modrinth','old',None,'Old',None,None),))
        generation=controller._translation_generation
        controller.request_id+=1
        controller.results=[dict(source='Modrinth',project_id='new',description='New')]
        controller._translation_finished(generation,'translation',dict(signature=signature,translations={'0':{'summary':dict(text='过时结果',format='plain')}},pending=False,status=''),'')
        self.assertEqual(controller.results[0]['project_id'],'new')
        self.assertNotIn('translated_summary',controller.results[0])

    def test_source_change_clears_previous_translation_before_async_work(self):
        controller=self.window.download_page.content_page.controller
        self.manager.set_setting('translation.enabled',True)
        controller.view='detail'
        row=dict(source='Modrinth',project_id='same',title='Project',description='Old summary',body='Old body')
        row['_translation_source']=('https://translate.bugg.icu/v1','Modrinth','same','Project','Old summary','Old body',None)
        row.update(translated_summary='旧简介',translated_body='旧正文',display_summary='旧简介')
        controller.selected_project=row
        with patch.object(controller.translation_pool,'start'):
            controller._translation_tick()
            self.assertEqual(row['translated_body'],'旧正文')
            row['body']='Updated body'
            row['description']='Updated summary'
            controller._translation_tick()
            self.assertNotIn('translated_body',row)
            self.assertNotIn('translated_summary',row)
            self.assertEqual(row['display_summary'],'Updated summary')
