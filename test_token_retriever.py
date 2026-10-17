import contextlib
import io
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
import requests
from TokenRetriever import TokenRetriever


class TokenRetrieverTests(unittest.TestCase):
    def test_browser_failure_closes_callback_and_returns_promptly(self):
        retriever = TokenRetriever()
        self.assertIsNone(retriever.retrieve_token(browser_opener=lambda url: False))
        self.assertIn('navegador', retriever.last_error)

    def test_cancel_wakes_wait_and_releases_server(self):
        retriever = TokenRetriever()
        servers = []
        original = retriever._start_callback_server
        def start(port):
            server = original(port)
            servers.append(server)
            return server
        opened = threading.Event()
        with patch.object(retriever, '_start_callback_server', side_effect=start):
            worker = threading.Thread(target=lambda: retriever.retrieve_token(browser_opener=lambda url: opened.set() or True))
            worker.start()
            self.assertTrue(opened.wait(2))
            retriever.cancel()
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(servers[0].fileno(), -1)
        self.assertFalse(servers[0].callback_thread.is_alive())

    def test_callback_exchanges_code_without_printing_token(self):
        retriever = TokenRetriever()
        response = Mock(status_code=200)
        response.json.return_value = {'success': True, 'data': {'oauth_token': 'synthetic-secret'}}
        captured = io.StringIO()
        with patch('TokenRetriever.requests.get', return_value=response) as exchange:
            # Use a separate real HTTP session for the loopback callback.
            def callback(url):
                port = parse_qs(urlsplit(url).query)['port'][0]
                with requests.Session() as session:
                    self.assertEqual(session.get(f'http://127.0.0.1:{port}/?success=true&code=test', timeout=2).status_code, 200)
                return True
            with contextlib.redirect_stdout(captured):
                self.assertEqual(retriever.retrieve_token(browser_opener=callback), 'synthetic-secret')
            exchange.assert_called_once()
        self.assertNotIn('synthetic-secret', captured.getvalue())

    def test_timeout_and_cancel_before_start(self):
        retriever = TokenRetriever()
        self.assertIsNone(retriever.retrieve_token(timeout=0, browser_opener=lambda url: True))
        self.assertIn('agotó', retriever.last_error)
        retriever = TokenRetriever()
        retriever.cancel()
        with patch.object(retriever, '_start_callback_server') as start:
            self.assertIsNone(retriever.retrieve_token())
            start.assert_not_called()

    def test_exchange_failure_does_not_echo_remote_body_or_exception(self):
        for response in [Mock(status_code=403, text='synthetic-secret'), Mock(status_code=200)]:
            response.json.return_value = {'success': False, 'message': 'synthetic-secret'}
            retriever = TokenRetriever()
            captured = io.StringIO()
            with patch('TokenRetriever.requests.get', return_value=response), contextlib.redirect_stdout(captured):
                self.assertIsNone(retriever._exchange_code_for_token('synthetic-code'))
            self.assertNotIn('synthetic-secret', captured.getvalue() + retriever.last_error)


if __name__ == '__main__':
    unittest.main()
