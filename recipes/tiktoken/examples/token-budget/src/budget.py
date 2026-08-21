"""Token accounting for a chat payload, and the cache that makes it work offline."""

import hashlib
import os
import shutil
import time

import tiktoken

MODEL = "gpt-4o"
ENCODING = tiktoken.encoding_name_for_model(MODEL)

# The blob tiktoken_ext.openai_public fetches for this encoding, and the name it is
# cached under: tiktoken keys its cache on sha1 of the URL, not on the encoding name.
VOCAB_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
CACHE_KEY = hashlib.sha1(VOCAB_URL.encode()).hexdigest()

# An app-chosen cap on what this screen will send, not the model's context window.
PROMPT_BUDGET = 512

# OpenAI's counting recipe: three tokens of framing per message, one more for a name
# field, and three that prime the reply. tiktoken itself tokenises text and knows
# nothing about roles or message boundaries.
TOKENS_PER_MESSAGE = 3
TOKENS_PER_NAME = 1
REPLY_PRIMING = 3

HISTORY = [
    {
        "role": "system",
        "content": (
            "You are a field assistant for a soil survey app. Answer in at most three "
            "sentences and never invent a measurement."
        ),
    },
    {
        "role": "user",
        "content": (
            "Plot 14 came back at pH 5.2 with 3% organic matter. Is that consistent "
            "with last season?"
        ),
    },
    {
        "role": "assistant",
        "content": (
            "Last season plot 14 read pH 5.4 at 2.8% organic matter, so both moved "
            "slightly and neither moved beyond the sampling error you recorded "
            "(plus or minus 0.3 pH)."
        ),
    },
]

DRAFT = (
    "Draft a note for the landowner summarising plots 12 to 16, and flag anything "
    "that drifted more than half a pH point since last season."
)

SAMPLES = {
    "English prose": (
        "The quick brown fox jumps over the lazy dog, and then does so again, rather "
        "more slowly, because the afternoon has grown warm."
    ),
    "Python source": (
        "def budget(messages, limit):\n"
        "    used = count_chat(enc, messages)\n"
        "    return max(limit - used, 0)\n"
    ),
    "JSON payload": (
        '{"model":"gpt-4o","messages":[{"role":"user","content":"hi"}],'
        '"temperature":0.2,"max_tokens":512}'
    ),
    "Japanese": "東京の天気は明日から崩れる見込みです。傘を持って出かけてください。",
    "Emoji": "🚀🌍🐍✨🎯🔥💡📦🧭🛰️",
}


def cache_dir():
    """Create and return the directory tiktoken will keep vocabulary blobs in.

    FLET_APP_STORAGE_CACHE is the app-private location for files that could be
    regenerated, which is exactly what a downloaded vocabulary is.
    """
    path = os.path.join(os.getenv("FLET_APP_STORAGE_CACHE", "."), "tiktoken")
    os.makedirs(path, exist_ok=True)
    return path


def bundled_vocab():
    """Return the path of the vocabulary shipped in assets, or None if absent.

    Prefetching the blob into src/assets/tiktoken/ before `flet build` is what turns a
    first launch on a plane from an exception into a token count.
    """
    assets = os.getenv("FLET_ASSETS_DIR")
    if not assets:
        return None
    path = os.path.join(assets, "tiktoken", CACHE_KEY)
    return path if os.path.isfile(path) else None


def prepare():
    """Load the encoding from the nearest copy of the vocabulary, and say which one.

    tiktoken reads TIKTOKEN_CACHE_DIR each time it loads an encoding and looks for a
    file named after the sha1 of the blob URL. A hit is a plain file read: no socket
    is opened, and the directory may be read-only. A miss goes to the network, and on
    a device with no network `tiktoken.encoding_for_model` raises
    requests.exceptions.ConnectionError rather than returning a tokeniser.

    Returns the Encoding, where its bytes came from, and how long the load took.
    """
    directory = cache_dir()
    os.environ["TIKTOKEN_CACHE_DIR"] = directory
    target = os.path.join(directory, CACHE_KEY)

    source = "on-device cache"
    if not os.path.isfile(target):
        bundle = bundled_vocab()
        if bundle:
            shutil.copyfile(bundle, target)
            source = "bundled asset"
        else:
            source = "network"

    started = time.perf_counter()
    encoding = tiktoken.encoding_for_model(MODEL)
    return encoding, source, (time.perf_counter() - started) * 1000


def conversation(draft):
    """Build the payload that would be sent: fixed history plus the typed message."""
    return [*HISTORY, {"role": "user", "content": draft}]


def count_chat(encoding, messages):
    """Count the tokens a chat payload costs, message framing included.

    Encoding the concatenated content undercounts, because every message carries
    framing the API charges for. Summing the parts is the app's job; tiktoken only
    supplies the count for each string.

    disallowed_special=() is load-bearing, not tidiness: encode() defaults to
    raising ValueError on text that spells a special token, so a user who types
    <|endoftext|> into the field would otherwise take the whole count down.
    """
    total = REPLY_PRIMING
    for message in messages:
        total += TOKENS_PER_MESSAGE
        for key, value in message.items():
            total += len(encoding.encode(value, disallowed_special=()))
            if key == "name":
                total += TOKENS_PER_NAME
    return total


def ratios(encoding):
    """Characters, tokens and characters per token for each sample text.

    The spread is the point. A rule of thumb of four characters per token holds for
    English prose and falls apart everywhere else, so a character budget is not a
    token budget.
    """
    rows = []
    for name, text in SAMPLES.items():
        tokens = len(encoding.encode(text))
        rows.append((name, len(text), tokens, len(text) / tokens))
    return rows
