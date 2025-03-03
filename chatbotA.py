import streamlit as st
from PyPDF2 import PdfReader
from langchain.text_splitter import RecursiveCharacterTextSplitter
import os
from langchain_google_genai import GoogleGenerativeAIEmbeddings
import google.generativeai as genai
from langchain.vectorstores import FAISS
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains.question_answering import load_qa_chain
from langchain.prompts import PromptTemplate
from dotenv import load_dotenv
from docx import Document
import csv
import datetime
import fitz
import pytesseract
from PIL import Image
import fitz  # PyMuPDF
import cv2
import numpy as np

import io
import base64

pytesseract.pytesseract.tesseract_cmd = r"C:/Program Files/Tesseract-OCR/tesseract.exe"

import os

load_dotenv()

# Load the Google Generative AI Embeddings
os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Langsmith api load
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = os.getenv("LANGCHAIN_API_KEY")

# Initialize search history list
search_history = []

# Check if the search history CSV file exists, and create it if not
history_file = "search_history.csv"
if not os.path.exists(history_file):
    with open(history_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Query", "Response", "Timestamp"])  # Add "Timestamp" header


# Function to save search history to the CSV file
def save_search_history_to_file():
    with open(history_file, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        for item in search_history:
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow([item["query"], item["response"], timestamp])


def load_and_clean_search_history():
    """Loads and cleans search history older than 24 hours."""
    now = datetime.datetime.now()
    new_history = []
    with open(history_file, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        header = next(reader)  # Skip header row
        for row in reader:
            timestamp = datetime.datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
            if (now - timestamp).total_seconds() < 86400:  # 24 hours = 86400 seconds
                new_history.append(
                    {"query": row[0], "response": row[1], "timestamp": row[2]}
                )

    # Rewrite the CSV with only the recent history
    with open(history_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Query", "Response", "Timestamp"])  # Write header again
        for item in new_history:
            writer.writerow([item["query"], item["response"], item["timestamp"]])

    return new_history


# Function to save the uploaded file
def save_uploaded_file(uploaded_file):
    directory = "saved_files"  # Specify your directory name
    if not os.path.exists(directory):
        os.makedirs(directory)  # Create the directory if it does not exist

    file_path = os.path.join(directory, uploaded_file.name)
    # Write the uploaded file to the new file path
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return file_path


# Function to extract text from PDF using OCR
def extract_text_from_pdf_ocr(pdf_path):
    extracted_text = ""
    # Open PDF file
    with fitz.open(pdf_path) as pdf_document:
        for page_num in range(len(pdf_document)):
            page = pdf_document.load_page(page_num)

            # Convert PDF page to grayscale image
            image_bytes = page.get_pixmap().tobytes()
            image = np.frombuffer(image_bytes, np.uint8)
            image = cv2.imdecode(image, cv2.IMREAD_GRAYSCALE)

            # Apply preprocessing techniques
            # Binarization
            _, binary_image = cv2.threshold(
                image, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
            )
            # Noise reduction
            denoised_image = cv2.fastNlMeansDenoising(binary_image, None, 10, 7, 21)

            # Perform OCR on preprocessed image
            page_text = pytesseract.image_to_string(Image.fromarray(denoised_image))
            extracted_text += page_text + "\n"

    return extracted_text.strip()


# Function to get text from various document types
def get_document_text(files, use_ocr=False):
    text = ""
    for file in files:
        save_uploaded_file(file)
        # Save the uploaded file
        if file.name.lower().endswith(".pdf"):
            if use_ocr:
                file_path = save_uploaded_file(file)
                text += extract_text_from_pdf_ocr(file_path)
            else:
                pdf_reader = PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() or ""
        elif file.name.lower().endswith(".docx"):
            doc = Document(file)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif file.name.lower().endswith(".csv"):
            file.seek(0)  # Go to the start of the file
            reader = csv.reader(file.read().decode("utf-8").splitlines())
            for row in reader:
                text += ", ".join(row) + "\n"
        else:
            print(f"Skipping unsupported file format: {file.name}")
    return text


def get_text_chunks(text):
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=10000, chunk_overlap=1000)
    chunks = text_splitter.split_text(text)
    return chunks


@st.cache_resource
def get_vector_store(text_chunks):
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    vector_store = FAISS.from_texts(text_chunks, embedding=embeddings)
    vector_store.save_local("faiss_index")


# Function to save search history
def save_search_history(query, response):
    history_item = {"query": query, "response": response}
    search_history.append(history_item)
    # Save to file after appending
    save_search_history_to_file()


# Function to load search history from the CSV file
def load_search_history_from_file():
    with open(history_file, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        next(reader)  # Skip header row
        for row in reader:
            search_history.append({"query": row[0], "response": row[1]})


# Function to display search history
def display_search_history():
    load_search_history_from_file()
    st.sidebar.subheader("Search History")
    for item in search_history:
        st.sidebar.write(
            f"<span style='color: orange'><b>Query:</b></span> {item['query']}<br><span style='color: orange'><b>Response:</b></span> {item['response']}<br>",
            unsafe_allow_html=True,
        )


# Function to delete chat history from the CSV file
def delete_chat_history():
    with open(history_file, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Query", "Response"])  # Rewrite header row only


# Function to handle user input and chatbot response
def user_input(user_question, pdf_docs):
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    new_db = FAISS.load_local(
        "faiss_index", embeddings, allow_dangerous_deserialization=True
    )
    docs = new_db.similarity_search(user_question)
    chain = get_conversational_chain()
    response = chain(
        {"input_documents": docs, "question": user_question}, return_only_outputs=True
    )
    save_search_history(user_question, response["output_text"])

    with st.chat_message("user"):
        st.write(user_question)
    # with st.chat_message(name="user", avatar="🤔"):
    #     st.write(user_question)
    # with st.chat_message(name="assistant", avatar="🤖"):
    #     st.write(response["output_text"])
    with st.chat_message("assistant"):
        st.write(response["output_text"])


def get_conversational_chain():
    prompt_template = """
    Answer all the questions given in the prompt, answer like a friend\n\n
    Context:\n {context}?\n
    Question: \n{question}\n

    Answer:
    """

    model = ChatGoogleGenerativeAI(model="gemini-pro", temperature=0.3)

    prompt = PromptTemplate(
        template=prompt_template, input_variables=["context", "question"]
    )
    chain = load_qa_chain(model, chain_type="stuff", prompt=prompt)

    return chain


# Main function
def main():
    st.set_page_config("Chat PDF", page_icon="📄", layout="wide")
    # Custom CSS to improve aesthetics
    st.markdown(
        """
    <style>
    .big-font {
        font-size:20px !important;
        font-weight: bold;
    }
    .header-style {
        font-size:30px !important;
        font-weight: bold;
        color: #4A4AFF; /* Changed color for better visibility */
    }
    .streamlit-container {
        margin-top: 2rem;
    }
    .stButton>button {
        font-size: 20px;
        border-radius: 20px 20px; /* Rounded corners for the button */
        border: 2px solid #4A4AFF;
        color: #FFFFFF;
        # background-color: #4A4AFF;
    }

    .sidebar .sidebar-content {
        background-color: #4A4AFF;
    }
 
    .stTextInput>div>div>input {
        font-size: 18px;
    }
    .stFileUploader>div>div>span>button {
        font-size: 16px;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )
    # Header
    # st.markdown('<p class="header-style">📄 Chat with Documents  💁‍♂️</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="header-style">📄 ChatBot For Insurance  💁‍♂️</p>',
        unsafe_allow_html=True,
    )

    # Layout adjustments
    col1, col2 = st.columns([3, 2])

    with col2:
        st.markdown('<p class="big-font">Upload:</p>', unsafe_allow_html=True)

        # file upload for main
        # pdf_docs = st.file_uploader("Upload PDFs", accept_multiple_files=True, help="Upload PDFs from which you want to fetch answers.", type=['pdf'])
        pdf_docs = st.file_uploader(
            "",
            accept_multiple_files=True,
            help="Upload PDFs from which you want to fetch answers.",
            type=["pdf"],
        )

        use_ocr = st.checkbox("Use OCR")
        if use_ocr:
            ocr_files = pdf_docs
        else:
            ocr_files = None
        if st.button("Submit & Process"):
            with st.spinner("Processing..."):
                if not pdf_docs:
                    st.error("Please upload PDFs.")
                else:
                    raw_text = ""
                    if pdf_docs:
                        raw_text += get_document_text(
                            pdf_docs, use_ocr=(ocr_files is not None)
                        )
                    if ocr_files:
                        raw_text += get_document_text(ocr_files, use_ocr=True)
                    if raw_text:
                        text_chunks = get_text_chunks(raw_text)
                        if text_chunks:
                            get_vector_store(text_chunks)
                            st.success("Done. Ask away!")
                        else:
                            st.error("No text chunks found.")
                    else:
                        st.error("No text extracted from the documents.")
    with col1:
        st.markdown('<p class="big-font">Ask a Question:</p>', unsafe_allow_html=True)
        user_question = st.text_input(
            "",
            placeholder="Type your question here...",
            help="Type your question and press enter.",
        )
        # user_question = st.chat_input("Type your question here...")
        if user_question:
            user_input(user_question, pdf_docs)

        # st.sidebar.image("logo.png")
        st.sidebar.image("logo/1.png")
        st.sidebar.header("Menu:")
        if st.sidebar.button("Delete Chat History"):
            delete_chat_history()
            st.sidebar.success("Chat history deleted successfully.")
        # if st.sidebar.button("View Search History"):
        #     display_search_history()
        display_search_history()


if __name__ == "__main__":
    main()
