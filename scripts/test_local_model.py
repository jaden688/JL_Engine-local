from transformers import pipeline

print("Downloading and loading the financial sentiment model...")
# This will download the model weights (~300MB) and cache them locally
sentiment_pipeline = pipeline(
    "sentiment-analysis", 
    model="mrm8488/distilroberta-finetuned-financial-news-sentiment-analysis"
)

print("Model loaded successfully!")

# Test it
test_headlines = [
    "Fetch.ai announces major partnership with Bosch to build decentralized IoT network.",
    "Crypto markets crash as SEC announces new regulatory crackdown.",
    "Bitcoin remains stable at $65,000 amid low trading volume."
]

for headline in test_headlines:
    result = sentiment_pipeline(headline)[0]
    print(f"Headline: {headline}")
    print(f"Sentiment: {result['label']} (Confidence: {result['score']:.4f})\n")
