import logging

from chess_mcp.server.run import RedactTokenFilter, build_log_config, startup_notice


def test_filter_redacts_tokens_in_messages_and_args():
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, '%s - "WebSocket %s" [accepted]', ("1.2.3.4", "/ws?token=s3cr3t-Tok_en"), None)
    assert RedactTokenFilter().filter(record) is True
    assert "s3cr3t" not in record.getMessage()
    assert "token=<redacted>" in record.getMessage()


def test_log_config_filters_every_handler():
    config = build_log_config()
    for handler in config["handlers"].values():
        assert "redact_token" in handler["filters"]


def test_startup_notice_hides_token_when_not_a_terminal():
    text = startup_notice("http://h", "abc123", "/data/token", tty=False)
    assert "abc123" not in text
    assert "/data/token" in text
    assert "abc123" in startup_notice("http://h", "abc123", "/data/token", tty=True)
