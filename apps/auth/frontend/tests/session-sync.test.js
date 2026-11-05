import test from "node:test";
import assert from "node:assert/strict";


class FakeBroadcastChannel {
  static instance = null;

  constructor() {
    FakeBroadcastChannel.instance = this;
    this.listener = null;
  }

  addEventListener(_name, listener) {
    this.listener = listener;
  }

  postMessage() {}

  emit(data) {
    this.listener?.({ data });
  }
}

globalThis.window = {
  BroadcastChannel: FakeBroadcastChannel,
  addEventListener() {},
  localStorage: {
    getItem: () => null,
    setItem() {},
    removeItem() {},
  },
  setTimeout,
};

const { subscribeLoginSessionState } = await import(
  "../../../../packages/platform-ui/src/session-sync.js"
);


test("cross-tab session messages apply remote identity and logout", () => {
  const received = [];
  const unsubscribe = subscribeLoginSessionState((session) => received.push(session));
  FakeBroadcastChannel.instance.emit({ messageId: "identity-change", sourceId: "another-tab", session: { userId: "target" } });
  FakeBroadcastChannel.instance.emit({ messageId: "logout", sourceId: "another-tab", session: null });
  unsubscribe();
  assert.deepEqual(received, [{ userId: "target" }, null]);
});

test("the same cross-tab message is applied only once", () => {
  const received = [];
  const unsubscribe = subscribeLoginSessionState((session) => received.push(session));
  const message = { messageId: "same-message", sourceId: "another-tab", session: { userId: "target" } };
  FakeBroadcastChannel.instance.emit(message);
  FakeBroadcastChannel.instance.emit(message);
  unsubscribe();
  assert.deepEqual(received, [{ userId: "target" }]);
});
