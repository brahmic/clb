import { ChatStateSchema, type ChatState } from "@/features/chat/schemas";

const DB_NAME = "codex-lb-dashboard-chat";
const STORE_NAME = "state";
const STATE_KEY = "dashboard-chat-state";
const ACTIVE_THREAD_KEY = "dashboard-chat-active-thread-id";
const LAST_MODEL_KEY = "dashboard-chat-last-model";
const LAST_ACCOUNT_KEY = "dashboard-chat-last-account";

let memoryState: ChatState = { threads: [] };

type ChatPreferences = {
  activeThreadId: string | null;
  lastModel: string | null;
  lastAccount: string | null;
};

function getIndexedDb(): IDBFactory | null {
  if (typeof window === "undefined" || !("indexedDB" in window)) {
    return null;
  }
  return window.indexedDB;
}

async function openDatabase(): Promise<IDBDatabase | null> {
  const indexedDb = getIndexedDb();
  if (indexedDb === null) {
    return null;
  }
  return await new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDb.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("Failed to open dashboard chat database"));
  });
}

export async function loadChatState(): Promise<ChatState> {
  const db = await openDatabase();
  if (db === null) {
    return memoryState;
  }
  return await new Promise<ChatState>((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readonly");
    const request = transaction.objectStore(STORE_NAME).get(STATE_KEY);
    request.onsuccess = () => {
      const parsed = ChatStateSchema.safeParse(request.result ?? { threads: [] });
      resolve(parsed.success ? parsed.data : { threads: [] });
    };
    request.onerror = () => reject(request.error ?? new Error("Failed to load dashboard chat state"));
  }).finally(() => {
    db.close();
  });
}

export async function saveChatState(state: ChatState): Promise<void> {
  memoryState = state;
  const db = await openDatabase();
  if (db === null) {
    return;
  }
  await new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readwrite");
    transaction.objectStore(STORE_NAME).put(state, STATE_KEY);
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error ?? new Error("Failed to save dashboard chat state"));
  }).finally(() => {
    db.close();
  });
}

function getStorageValue(key: string): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(key);
}

function setStorageValue(key: string, value: string | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (value === null) {
    window.localStorage.removeItem(key);
    return;
  }
  window.localStorage.setItem(key, value);
}

export function loadChatPreferences(): ChatPreferences {
  return {
    activeThreadId: getStorageValue(ACTIVE_THREAD_KEY),
    lastModel: getStorageValue(LAST_MODEL_KEY),
    lastAccount: getStorageValue(LAST_ACCOUNT_KEY),
  };
}

export function saveChatPreferences(preferences: ChatPreferences): void {
  setStorageValue(ACTIVE_THREAD_KEY, preferences.activeThreadId);
  setStorageValue(LAST_MODEL_KEY, preferences.lastModel);
  setStorageValue(LAST_ACCOUNT_KEY, preferences.lastAccount);
}

