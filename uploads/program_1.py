# Import required libraries
import nltk
import string
from nltk.tokenize import word_tokenize
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer, WordNetLemmatizer
from collections import Counter

# Download required NLTK resources
nltk.download('punkt')
nltk.download('stopwords')
nltk.download('wordnet')
nltk.download('omw-1.4')

# Tokenization
def tokenize_text(text):
    tokens = word_tokenize(text)
    print("In Word Tokens:", tokens)
    return tokens

# Remove punctuation
def remove_punctuation(tokens):
    tokens_no_punct = [word for word in tokens if word not in string.punctuation]
    print("In Tokens Without Punctuation:", tokens_no_punct)
    return tokens_no_punct

# Convert to lowercase
def convert_to_lowercase(tokens):
    tokens_lower = [word.lower() for word in tokens]
    print("In Tokens in Lowercase:", tokens_lower)
    return tokens_lower

# Remove stopwords
def remove_stopwords(tokens):
    stop_words = set(stopwords.words('english'))
    tokens_no_stopwords = [word for word in tokens if word not in stop_words]
    print("In Tokens Without Stopwords:", tokens_no_stopwords)
    return tokens_no_stopwords

# Analyze word frequencies
def analyze_word_frequencies(tokens):
    word_frequencies = Counter(tokens)
    print("In Word Frequencies:")
    for word, freq in word_frequencies.items():
        print(f"{word}: {freq}")
    return word_frequencies

# Stemming
def stem_words(tokens):
    stemmer = PorterStemmer()
    stemmed_tokens = [stemmer.stem(word) for word in tokens]
    print("In Stemmed Words:", stemmed_tokens)
    return stemmed_tokens

# Lemmatization
def lemmatize_words(tokens):
    lemmatizer = WordNetLemmatizer()
    lemmatized_tokens = [lemmatizer.lemmatize(word) for word in tokens]
    print("In Lemmatized Words:", lemmatized_tokens)
    return lemmatized_tokens

# Main word analysis function
def word_analysis(text):
    print("Original Text:", text)
    tokens = tokenize_text(text)
    tokens_no_punct = remove_punctuation(tokens)
    tokens_lower = convert_to_lowercase(tokens_no_punct)
    tokens_no_stopwords = remove_stopwords(tokens_lower)
    word_frequencies = analyze_word_frequencies(tokens_no_stopwords)
    stemmed_tokens = stem_words(tokens_no_stopwords)
    lemmatized_tokens = lemmatize_words(tokens_no_stopwords)
    return stemmed_tokens, lemmatized_tokens

# Input text
text = "Natural Language Processing is a fascinating area of computer science "

print("Experiment 1: Word Analysis")
stemmed_tokens, lemmatized_tokens = word_analysis(text)

print("\nFinal Output:")
print("Stemmed Tokens:", stemmed_tokens)
print("Lemmatized Tokens:", lemmatized_tokens)
