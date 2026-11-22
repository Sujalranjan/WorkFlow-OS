"""Gmail client methods used for incremental trigger sync (read-only), against a fake Gmail API."""

import pytest

from app.services.gmail_client import GmailApiClient, GmailApiError, GmailHistoryExpired


class _Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeGmail:
    """Just enough of the googleapiclient resource shape: users().messages()/history()/getProfile()."""

    def __init__(self, message_ids, history_pages=None, history_status=None, history_id="900"):
        self.message_ids = message_ids
        self.history_pages = history_pages or []
        self.history_status = history_status
        self.history_id = history_id
        self.list_calls = []

    # resource navigation
    def users(self):
        return self

    def messages(self):
        return self

    def history(self):
        return _History(self)

    def getProfile(self, userId):
        return _Call(lambda: {"emailAddress": "ops@example.com", "historyId": self.history_id})

    def list(self, userId, q, maxResults, pageToken=None):
        self.list_calls.append((q, maxResults, pageToken))
        start = int(pageToken or 0)
        page = self.message_ids[start:start + maxResults]
        nxt = start + maxResults
        body = {"messages": [{"id": m, "threadId": f"t-{m}"} for m in page]}
        if nxt < len(self.message_ids):
            body["nextPageToken"] = str(nxt)
        return _Call(lambda: body)


class _History:
    def __init__(self, fake):
        self.fake = fake

    def list(self, userId, startHistoryId, historyTypes, maxResults, pageToken=None):
        def run():
            if self.fake.history_status:
                err = Exception("HttpError")
                err.resp = type("Resp", (), {"status": self.fake.history_status})()
                raise err
            index = int(pageToken or 0)
            page = dict(self.fake.history_pages[index])
            if index + 1 < len(self.fake.history_pages):
                page["nextPageToken"] = str(index + 1)
            return page

        return _Call(run)


def client(fake):
    return GmailApiClient(service=fake)


def test_list_message_ids_reads_every_page_up_to_the_limit():
    ids = [f"m{n}" for n in range(1234)]
    fake = FakeGmail(ids)
    assert client(fake).list_message_ids("has:attachment") == ids
    assert [c[2] for c in fake.list_calls] == [None, "500", "1000"]
    assert len(client(FakeGmail(ids)).list_message_ids("x", limit=700)) == 700
    with pytest.raises(ValueError):
        client(fake).list_message_ids("  ")


def test_history_reports_added_messages_across_pages():
    pages = [
        {"historyId": "950", "history": [{"id": "901", "labelsAdded": [{}]}]},
        {"historyId": "960", "history": [{"id": "955", "messagesAdded": [{"message": {"id": "m9"}}]}]},
    ]
    assert client(FakeGmail([], history_pages=pages)).messages_added_since("900") == (True, "960")


def test_history_without_new_messages_returns_the_latest_id():
    pages = [{"historyId": "905"}]  # nothing happened
    assert client(FakeGmail([], history_pages=pages)).messages_added_since("900") == (False, "905")


def test_expired_history_id_is_reported_distinctly():
    with pytest.raises(GmailHistoryExpired):
        client(FakeGmail([], history_status=404)).messages_added_since("1")
    with pytest.raises(GmailApiError):
        client(FakeGmail([], history_status=500)).messages_added_since("1")


def test_current_history_id_comes_from_the_profile():
    assert client(FakeGmail([], history_id="12345")).current_history_id() == "12345"
