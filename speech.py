"""Part 5: speech to text with Faster-Whisper, in English and Arabic.
The model runs on this computer, so it needs no API key and uses none of the Gemini quota.
Part 6 (FastAPI) gives the text to analyze() from part 4, like a typed question.
"""
import io

from faster_whisper import WhisperModel

# "small" is multilingual. "base" is faster but makes more mistakes in Arabic; "medium" is better but slow on a CPU.
MODEL_SIZE = "small"
AUDIO_TYPES = (".wav", ".mp3", ".m4a", ".ogg", ".webm")   # .webm is what a browser records

# A short text in the language of the question, with words that questions about data often use.
# Whisper reads it before the recording, so it expects these words and writes them correctly
# (for example "أعلى مبيعات" instead of "أعلام بيعات").
PROMPTS = {
    "ar": "سؤال عن تحليل البيانات: المبيعات، الطلبات، الفئات، المدن، المنتجات، الكمية، السعر، المجموع، أعلى، أقل.",
    "en": "A question about data analysis: sales, orders, categories, cities, products, quantity, price, total, highest, lowest.",
}

model = None   # loaded the first time it is needed


def get_model():
    """Load the model once: the first time it is downloaded (about 500 MB), then it is read from the disk."""
    global model   # we change the variable of the file, not a new local one
    if model is None:
        # int8: smaller numbers inside the model, so it is faster on a CPU and uses less memory
        model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return model


def transcribe(data, language=None):
    """Turn the bytes of an audio file into text.
    language: "en" or "ar" if the user chose it, or None to let Whisper detect it."""
    # Example: the recording of "Show me total sales by product category" returns
    #   {"text": "Show me total sales by product category.", "language": "en"}
    segments, info = get_model().transcribe(
        io.BytesIO(data),   # the uploaded file is bytes in memory: BytesIO lets Whisper read it like a file
        language=language,
        initial_prompt=PROMPTS.get(language),   # None when Whisper detects the language
        vad_filter=True,    # skip the silent parts, so Whisper does not invent words in the silence
    )
    # Whisper cuts the speech into segments (parts of a few seconds). They are made while we read them.
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text:
        raise ValueError("No speech was found in the recording.")
    return {"text": text, "language": info.language}


if __name__ == "__main__":
    import sys
    import time
    from pathlib import Path

    # python speech.py          ->  the small model
    # python speech.py medium   ->  another size, to compare the text and the time
    if len(sys.argv) > 1:
        MODEL_SIZE = sys.argv[1]

    start = time.time()
    get_model()
    print(f"Model {MODEL_SIZE} loaded in {time.time() - start:.1f} seconds")

    # Put short recordings in sample_data. The file name gives the language:
    # question_en.m4a -> English, question_ar.m4a or question_ar_dialect.m4a -> Arabic, other names -> detected
    files = [path for path in Path("sample_data").iterdir() if path.suffix.lower() in AUDIO_TYPES]
    if not files:
        print("No recordings found in sample_data. Supported types:", ", ".join(AUDIO_TYPES))
    for path in files:
        if "_en" in path.stem:
            language = "en"
        elif "_ar" in path.stem:
            language = "ar"
        else:
            language = None
        start = time.time()
        result = transcribe(path.read_bytes(), language)
        print(f"===== {path.name} | language: {result['language']} | {time.time() - start:.1f} seconds")
        print(result["text"])
