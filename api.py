from fastapi import FastAPI, Query, HTTPException
from typing import List, Dict
import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from langchain_chroma import Chroma
from langchain_community.embeddings.sentence_transformer import SentenceTransformerEmbeddings
import tensorflow as tf  # Make sure TensorFlow is imported to use the model

# Load your data
books = pd.read_csv("books_data_clean.csv")
rating = pd.read_csv("books_rating_clean.csv")
final_ratings = pd.read_csv("final_ratings.csv")
merged_df = pd.merge(rating, books, on='Title')


# Load the pre-trained recommendation model
model = tf.keras.models.load_model("Colab_User")
# Map user ID to a "user vector" via an embedding matrix
user_ids = merged_df["User_id"].unique().tolist()
user2user_encoded = {x: i for i, x in enumerate(user_ids)}
userencoded2user = {i: x for i, x in enumerate(user_ids)}
# Map books ID to a "books vector" via an embedding matrix
book_ids = merged_df["Title"].unique().tolist()
book2book_encoded = {x: i for i, x in enumerate(book_ids)}
book_encoded2book = {i: x for i, x in enumerate(book_ids)}
merged_df["user"] = merged_df["User_id"].map(user2user_encoded)
merged_df["book"] = merged_df["Title"].map(book2book_encoded)
num_users = len(user2user_encoded)
num_books = len(book_encoded2book)
merged_df['rating'] = merged_df['review/score'].values.astype(np.float32)


# Create pivot table and calculate similarity score
pivot_table = final_ratings.pivot_table(index='Title', columns='User_id', values='review/score')
pivot_table.fillna(0, inplace=True)
similarity_score = cosine_similarity(pivot_table)

app = FastAPI()

# Collaborative filtering recommendation function
@app.get("/colabBook/")
async def recommend(id_book: int = Query(...), amount: int = Query(...)):
    try:
        book_name = books.loc[books.iloc[:, 0] == id_book, 'Title'].values[0]
    except IndexError:
        raise HTTPException(status_code=404, detail="Book ID not found")
    
    if book_name not in pivot_table.index:
        raise HTTPException(status_code=404, detail="Book title not found in pivot table")

    index = np.where(pivot_table.index == book_name)[0][0]
    similar_books = sorted(list(enumerate(similarity_score[index])), key=lambda x: x[1], reverse=True)[1:amount + 1]

    data = []
    for i in similar_books:
        temp_book = books[books['Title'] == pivot_table.index[i[0]]]
        item = {
            "title": temp_book.drop_duplicates('Title')['Title'].values[0],
            "authors": temp_book.drop_duplicates('Title')['authors'].values[0],
            "image": temp_book.drop_duplicates('Title')['image'].values[0]
        }
        data.append(item)
    return data

# Vector-based recommendation endpoint
@app.get("/recommendation/")
async def recommendation(id_book: List[int] = Query(...)):
    persist_directory = "db"
    embedding = SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")

    vectordb = Chroma(persist_directory=persist_directory, embedding_function=embedding)

    k_recommendation = max(1, round(100 / len(id_book)))
    
    all_recommendation = []
    for book_recomen in id_book:
        book_recomen = str(book_recomen)
        similarity_questions = vectordb.similarity_search(book_recomen, k=k_recommendation)

        docs = similarity_questions[1::]
    
        recommendation_list = []
        for doc in docs:
            row_value = doc.metadata.get("row")
            recommendation_list.append(row_value)

        all_recommendation.extend(recommendation_list)
    
    recommendation_indices = list(np.array(all_recommendation).flatten().tolist())

    return {"recommendations": recommendation_indices}

# Collaborative filtering recommendation for a user
@app.get("/colabUser/")
async def recommend_for_user(user_id: str = Query(...), amount: int = Query(...)):
    books_watched_by_user = merged_df[merged_df.User_id == user_id]
    books_not_watched = books[~books['Title'].isin(books_watched_by_user.Title.values)]['Title']

    books_not_watched = list(set(books_not_watched).intersection(set(book2book_encoded.keys())))

    books_not_watched = [[book2book_encoded.get(x)] for x in books_not_watched]

    user_encoder = user2user_encoded.get(user_id)

    if user_encoder is None:
        raise HTTPException(status_code=404, detail="User ID not found")

    user_book_array = np.hstack(
        ([[user_encoder]] * len(books_not_watched), books_not_watched)
    )

    ratings = model.predict(user_book_array).flatten()
    top_ratings_indices = ratings.argsort()[-10:][::-1]
    recommended_book_ids = [
        book_encoded2book.get(books_not_watched[x][0]) for x in top_ratings_indices
    ]

    top_books_user = (
        books_watched_by_user.sort_values(by="rating", ascending=False)
        .head(5)
        .Title.values
    )
    books_rows = books[books["Title"].isin(top_books_user)]
    top_books = []
    for row in books_rows.itertuples():
        top_books.append({"title": row.Title, "categories": row.categories})

    recommended_books = books[books["Title"].isin(recommended_book_ids)]
    recommendations = []
    for row in recommended_books.itertuples():
        recommendations.append({"title": row.Title, "categories": row.categories})

    return {
        "user_id": user_id,
        "top_books_user": top_books,
        "recommended_books": recommendations
    }

# Endpoint for root
@app.get("/")
async def read_root():
    return {"message": "Hello World"}
