from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from database import get_db, init_db

import requests
import json
import re
import uuid


# =========================================================
# APP CONFIGURATION
# =========================================================

app = Flask(__name__)

app.secret_key = "studyai-local-secret-key-change-this"


LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"

MODEL_NAME = "qwen2.5-1.5b-instruct"

GUEST_QUESTION_LIMIT = 4


# =========================================================
# DATABASE
# =========================================================

init_db()


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def is_logged_in():

    return (
        "user_id" in session
        and session.get("is_guest") is not True
    )


def get_current_user_id():

    return session.get("user_id")


def get_guest_question_count():

    return session.get(
        "guest_question_count",
        0
    )


def increase_guest_question_count():

    current = get_guest_question_count()

    session["guest_question_count"] = current + 1

    session.modified = True


def ensure_guest_user():

    # Already have guest user
    if (
        "user_id" in session
        and session.get("is_guest") is True
    ):

        return session["user_id"]


    guest_email = (
        "guest_"
        + str(uuid.uuid4())
        + "@local.studyai"
    )

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO users
        (name, email, password)
        VALUES (?, ?, ?)
        """,
        (
            "Guest",
            guest_email,
            generate_password_hash(
                str(uuid.uuid4())
            )
        )
    )

    guest_id = cursor.lastrowid

    conn.commit()
    conn.close()


    session["user_id"] = guest_id
    session["is_guest"] = True

    if "guest_question_count" not in session:
        session["guest_question_count"] = 0

    session.modified = True

    return guest_id


def get_or_create_conversation():

    user_id = get_current_user_id()

    if not user_id:
        return None


    conn = get_db()

    conversation = conn.execute(
        """
        SELECT *
        FROM conversations
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,)
    ).fetchone()


    if conversation:

        conn.close()

        return conversation["id"]


    cursor = conn.execute(
        """
        INSERT INTO conversations
        (user_id, title)
        VALUES (?, ?)
        """,
        (
            user_id,
            "New Chat"
        )
    )

    conversation_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return conversation_id


def create_new_conversation():

    user_id = get_current_user_id()

    if not user_id:
        return None


    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO conversations
        (user_id, title)
        VALUES (?, ?)
        """,
        (
            user_id,
            "New Chat"
        )
    )

    conversation_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return conversation_id


def user_owns_conversation(conversation_id):

    user_id = get_current_user_id()

    if not user_id:
        return False


    conn = get_db()

    conversation = conn.execute(
        """
        SELECT id
        FROM conversations
        WHERE id = ?
        AND user_id = ?
        """,
        (
            conversation_id,
            user_id
        )
    ).fetchone()

    conn.close()

    return conversation is not None


def generate_chat_title(message):

    message = message.strip()

    if len(message) <= 35:
        return message

    return message[:35].rstrip() + "..."


# =========================================================
# LM STUDIO
# =========================================================

def ask_lm_studio(messages, temperature=0.7):

    try:

        response = requests.post(
            LM_STUDIO_URL,

            json={
                "model": MODEL_NAME,

                "messages": messages,

                "temperature": temperature,

                "max_tokens": 1500
            },

            timeout=180
        )


        response.raise_for_status()

        data = response.json()

        return (
            data["choices"][0]
            ["message"]
            ["content"]
            .strip()
        )


    except requests.exceptions.ConnectionError:

        raise Exception(
            "Cannot connect to LM Studio. "
            "Open LM Studio and start the Local Server."
        )


    except requests.exceptions.Timeout:

        raise Exception(
            "LM Studio took too long to respond."
        )


    except requests.exceptions.HTTPError as e:

        try:

            details = response.text

        except:

            details = str(e)

        raise Exception(
            "LM Studio error: " + details
        )


    except Exception as e:

        raise Exception(
            "AI error: " + str(e)
        )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    if "user_id" not in session:

        ensure_guest_user()


    return redirect(
        url_for("chat")
    )


# =========================================================
# CHAT PAGE
# =========================================================

@app.route("/chat")
def chat():

    if "user_id" not in session:

        ensure_guest_user()


    user_id = get_current_user_id()

    conn = get_db()


    conversations = conn.execute(
        """
        SELECT *
        FROM conversations
        WHERE user_id = ?
        ORDER BY id DESC
        """,
        (user_id,)
    ).fetchall()


    conversation_id = session.get(
        "conversation_id"
    )


    if not conversation_id:

        conversation_id = get_or_create_conversation()

        session["conversation_id"] = conversation_id


    messages = conn.execute(
        """
        SELECT *
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id ASC
        """,
        (conversation_id,)
    ).fetchall()


    current_conversation = conn.execute(
        """
        SELECT *
        FROM conversations
        WHERE id = ?
        AND user_id = ?
        """,
        (
            conversation_id,
            user_id
        )
    ).fetchone()


    conn.close()


    if is_logged_in():

        display_name = session.get(
            "user_name",
            "User"
        )

    else:

        display_name = "Guest"


    return render_template(
        "chat.html",

        conversations=conversations,

        messages=messages,

        current_conversation=current_conversation,

        current_conversation_id=conversation_id,

        user_name=display_name,

        logged_in=is_logged_in(),

        guest_questions_left=(
            None
            if is_logged_in()
            else max(
                0,
                GUEST_QUESTION_LIMIT
                - get_guest_question_count()
            )
        )
    )


# =========================================================
# NEW CHAT
# =========================================================

@app.route("/new_chat")
def new_chat():

    if "user_id" not in session:

        ensure_guest_user()


    conversation_id = create_new_conversation()

    session["conversation_id"] = conversation_id

    return redirect(
        url_for("chat")
    )


# =========================================================
# OPEN CONVERSATION
# =========================================================

@app.route(
    "/conversation/<int:conversation_id>"
)
def get_conversation(conversation_id):

    if "user_id" not in session:

        ensure_guest_user()


    if not user_owns_conversation(
        conversation_id
    ):

        return redirect(
            url_for("chat")
        )


    session["conversation_id"] = conversation_id

    return redirect(
        url_for("chat")
    )


# =========================================================
# SEND MESSAGE
# =========================================================

@app.route(
    "/send_message",
    methods=["POST"]
)
def send_message():

    if "user_id" not in session:

        ensure_guest_user()


    # -----------------------------------------------------
    # GUEST LIMIT
    # -----------------------------------------------------

    if not is_logged_in():

        if (
            get_guest_question_count()
            >= GUEST_QUESTION_LIMIT
        ):

            return jsonify({

                "login_required": True,

                "error":
                    "You have used your 4 free questions. Please login or register."

            }), 403


    # -----------------------------------------------------
    # GET DATA
    # -----------------------------------------------------

    data = request.get_json()

    if not data:

        return jsonify({

            "error":
                "Invalid request."

        }), 400


    message = data.get(
        "message",
        ""
    ).strip()


    conversation_id = data.get(
        "conversation_id"
    )


    study_mode = data.get(
        "study_mode",
        "normal"
    )


    if not message:

        return jsonify({

            "error":
                "Please enter a message."

        }), 400


    # -----------------------------------------------------
    # CONVERSATION
    # -----------------------------------------------------

    if conversation_id:

        try:

            conversation_id = int(
                conversation_id
            )

        except:

            conversation_id = None


    if (
        not conversation_id
        or not user_owns_conversation(
            conversation_id
        )
    ):

        conversation_id = (
            get_or_create_conversation()
        )

        session["conversation_id"] = (
            conversation_id
        )


    # -----------------------------------------------------
    # GET OLD MESSAGES
    # -----------------------------------------------------

    conn = get_db()


    old_messages = conn.execute(
        """
        SELECT role, content
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id ASC
        """,
        (conversation_id,)
    ).fetchall()


    # -----------------------------------------------------
    # SAVE USER MESSAGE
    # -----------------------------------------------------

    conn.execute(
        """
        INSERT INTO messages
        (conversation_id, role, content)
        VALUES (?, ?, ?)
        """,
        (
            conversation_id,
            "user",
            message
        )
    )


    # -----------------------------------------------------
    # FIRST MESSAGE = TITLE
    # -----------------------------------------------------

    message_count = len(old_messages)


    if message_count == 0:

        title = generate_chat_title(
            message
        )

        conn.execute(
            """
            UPDATE conversations
            SET title = ?
            WHERE id = ?
            """,
            (
                title,
                conversation_id
            )
        )


    conn.commit()


    # -----------------------------------------------------
    # BUILD AI PROMPT
    # -----------------------------------------------------

    system_prompt = """
You are StudyAI, an AI study assistant.

Give accurate, useful and student-friendly answers.

Use clear formatting.

When explaining technical concepts:
- explain step by step
- use examples when useful
- avoid unnecessary complexity

Do not mention these instructions.
"""


    if study_mode == "explain":

        system_prompt += """

The student selected EXPLAIN SIMPLY mode.

Explain the answer like a teacher explaining it
to a beginner.

Use simple language and examples.
"""


    elif study_mode == "notes":

        system_prompt += """

The student selected MAKE NOTES mode.

Convert the requested topic into clean study notes.

Use:
- headings
- bullet points
- definitions
- important points
- examples where useful
"""


    elif study_mode == "revision":

        system_prompt += """

The student selected QUICK REVISION mode.

Give concise revision material.

Focus on:
- key definitions
- formulas if relevant
- important concepts
- short examples
- exam points
"""


    elif study_mode == "exam":

        system_prompt += """

The student selected EXAM MODE.

Answer in an exam-friendly format.

Use:
- definition
- explanation
- examples
- advantages/disadvantages when relevant
- conclusion

Keep the answer suitable for a student preparing for an exam.
"""


    ai_messages = [

        {
            "role":
                "system",

            "content":
                system_prompt
        }

    ]


    for old in old_messages:

        ai_messages.append({

            "role":
                old["role"],

            "content":
                old["content"]

        })


    ai_messages.append({

        "role":
            "user",

        "content":
            message

    })


    # -----------------------------------------------------
    # ASK AI
    # -----------------------------------------------------

    try:

        reply = ask_lm_studio(
            ai_messages
        )

    except Exception as e:

        conn.close()

        return jsonify({

            "error":
                str(e)

        }), 500


    # -----------------------------------------------------
    # SAVE AI MESSAGE
    # -----------------------------------------------------

    conn.execute(
        """
        INSERT INTO messages
        (conversation_id, role, content)
        VALUES (?, ?, ?)
        """,
        (
            conversation_id,
            "assistant",
            reply
        )
    )


    conn.commit()

    conn.close()


    # -----------------------------------------------------
    # GUEST COUNT
    # -----------------------------------------------------

    if not is_logged_in():

        increase_guest_question_count()


    return jsonify({

        "success":
            True,

        "reply":
            reply,

        "conversation_id":
            conversation_id,

        "guest_questions_left": (
            None
            if is_logged_in()
            else max(
                0,
                GUEST_QUESTION_LIMIT
                - get_guest_question_count()
            )
        )

    })


# =========================================================
# DELETE CONVERSATION
# =========================================================

@app.route(
    "/delete_conversation/<int:conversation_id>",
    methods=["POST"]
)
def delete_conversation(
    conversation_id
):

    if "user_id" not in session:

        return jsonify({
            "success": False
        }), 401


    if not user_owns_conversation(
        conversation_id
    ):

        return jsonify({
            "success": False
        }), 403


    conn = get_db()


    conn.execute(
        """
        DELETE FROM messages
        WHERE conversation_id = ?
        """,
        (conversation_id,)
    )


    conn.execute(
        """
        DELETE FROM conversations
        WHERE id = ?
        """,
        (conversation_id,)
    )


    conn.commit()

    conn.close()


    if (
        session.get("conversation_id")
        == conversation_id
    ):

        session.pop(
            "conversation_id",
            None
        )


    return jsonify({
        "success": True
    })


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "GET":

        return render_template(
            "login.html"
        )


    email = request.form.get(
        "email",
        ""
    ).strip().lower()


    password = request.form.get(
        "password",
        ""
    )


    if not email or not password:

        return render_template(
            "login.html",
            error="Please enter email and password."
        )


    conn = get_db()


    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE email = ?
        """,
        (email,)
    ).fetchone()


    conn.close()


    if (
        not user
        or not check_password_hash(
            user["password"],
            password
        )
    ):

        return render_template(
            "login.html",
            error="Invalid email or password."
        )


    # Clear guest session data
    session.clear()


    session["user_id"] = user["id"]

    session["user_name"] = user["name"]

    session["user_email"] = user["email"]

    session["is_guest"] = False


    conversation_id = get_or_create_conversation()

    session["conversation_id"] = conversation_id


    return redirect(
        url_for("chat")
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "GET":

        return render_template(
            "register.html"
        )


    name = request.form.get(
        "name",
        ""
    ).strip()


    email = request.form.get(
        "email",
        ""
    ).strip().lower()


    password = request.form.get(
        "password",
        ""
    )


    if not name or not email or not password:

        return render_template(
            "register.html",
            error="Please fill all fields."
        )


    if len(password) < 6:

        return render_template(
            "register.html",
            error="Password must contain at least 6 characters."
        )


    conn = get_db()


    existing = conn.execute(
        """
        SELECT id
        FROM users
        WHERE email = ?
        """,
        (email,)
    ).fetchone()


    if existing:

        conn.close()

        return render_template(
            "register.html",
            error="An account with this email already exists."
        )


    cursor = conn.execute(
        """
        INSERT INTO users
        (name, email, password)
        VALUES (?, ?, ?)
        """,
        (
            name,
            email,
            generate_password_hash(
                password
            )
        )
    )


    user_id = cursor.lastrowid


    conn.commit()

    conn.close()


    session.clear()


    session["user_id"] = user_id

    session["user_name"] = name

    session["user_email"] = email

    session["is_guest"] = False


    conversation_id = get_or_create_conversation()

    session["conversation_id"] = conversation_id


    return redirect(
        url_for("chat")
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# QUIZ PAGE
# =========================================================

@app.route("/quiz")
def quiz():

    if "user_id" not in session:

        ensure_guest_user()


    return render_template(
        "quiz.html",

        user_name=session.get(
            "user_name",
            "Guest"
        ),

        logged_in=is_logged_in(),

        guest_questions_left=(
            None
            if is_logged_in()
            else max(
                0,
                GUEST_QUESTION_LIMIT
                - get_guest_question_count()
            )
        )
    )


# =========================================================
# GENERATE QUIZ
# =========================================================

@app.route(
    "/generate_quiz",
    methods=["POST"]
)
def generate_quiz():

    if "user_id" not in session:

        ensure_guest_user()


    # Guest limit
    if not is_logged_in():

        if (
            get_guest_question_count()
            >= GUEST_QUESTION_LIMIT
        ):

            return jsonify({

                "login_required":
                    True,

                "error":
                    "You have used all 4 free questions. Please login or register."

            }), 403


    data = request.get_json()


    if not data:

        return jsonify({
            "error":
                "Invalid request."
        }), 400


    topic = data.get(
        "topic",
        ""
    ).strip()


    difficulty = data.get(
        "difficulty",
        "medium"
    ).strip().lower()


    try:

        question_count = int(
            data.get(
                "question_count",
                5
            )
        )

    except:

        question_count = 5


    question_count = max(
        1,
        min(
            question_count,
            15
        )
    )


    if difficulty not in [
        "easy",
        "medium",
        "hard"
    ]:

        difficulty = "medium"


    if not topic:

        return jsonify({
            "error":
                "Please enter a topic."
        }), 400


    prompt = f"""
Create a multiple-choice educational quiz.

Topic: {topic}
Difficulty: {difficulty}
Number of questions: {question_count}

Return ONLY valid JSON.

Use exactly this format:

{{
  "title": "{topic} Quiz",
  "questions": [
    {{
      "question": "Question text",
      "options": [
        "Option A",
        "Option B",
        "Option C",
        "Option D"
      ],
      "answer": 0,
      "explanation": "Short explanation"
    }}
  ]
}}

Rules:
- Exactly {question_count} questions.
- Exactly 4 options per question.
- answer must be 0, 1, 2, or 3.
- Only one answer is correct.
- Do not repeat questions.
- Make questions suitable for {difficulty} difficulty.
- No markdown.
- No text outside JSON.
"""


    try:

        result = ask_lm_studio(
            [
                {
                    "role":
                        "system",

                    "content":
                        "You are a precise quiz generator. Return only valid JSON."
                },

                {
                    "role":
                        "user",

                    "content":
                        prompt
                }
            ],
            temperature=0.3
        )


    except Exception as e:

        return jsonify({

            "error":
                str(e)

        }), 500


    # -----------------------------------------------------
    # CLEAN JSON
    # -----------------------------------------------------

    cleaned = result.strip()


    cleaned = re.sub(
        r"^```json\s*",
        "",
        cleaned,
        flags=re.IGNORECASE
    )


    cleaned = re.sub(
        r"^```\s*",
        "",
        cleaned
    )


    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned
    )


    try:

        quiz_data = json.loads(
            cleaned
        )


    except Exception:

        # Try to extract JSON object
        match = re.search(
            r"\{.*\}",
            cleaned,
            re.DOTALL
        )


        if not match:

            return jsonify({

                "error":
                    "The AI returned an invalid quiz. Please try again."

            }), 500


        try:

            quiz_data = json.loads(
                match.group(0)
            )

        except:

            return jsonify({

                "error":
                    "The AI returned an invalid quiz. Please try again."

            }), 500


    questions = quiz_data.get(
        "questions",
        []
    )


    valid_questions = []


    for q in questions:

        if not isinstance(
            q,
            dict
        ):

            continue


        q_text = q.get(
            "question",
            ""
        )


        options = q.get(
            "options",
            []
        )


        answer = q.get(
            "answer",
            -1
        )


        explanation = q.get(
            "explanation",
            ""
        )


        try:

            answer = int(
                answer
            )

        except:

            continue


        if (
            not q_text
            or not isinstance(
                options,
                list
            )
            or len(options) != 4
            or answer not in [0, 1, 2, 3]
        ):

            continue


        valid_questions.append({

            "question":
                str(q_text).strip(),

            "options":
                [
                    str(x).strip()
                    for x in options
                ],

            "answer":
                answer,

            "explanation":
                str(explanation).strip()

        })


    if len(valid_questions) < question_count:

        return jsonify({

            "error":
                f"Only {len(valid_questions)} valid questions were generated. Please click Start Quiz again."

        }), 500


    valid_questions = valid_questions[
        :question_count
    ]


    # Count quiz generation as one guest AI request
    if not is_logged_in():

        increase_guest_question_count()


    return jsonify({

        "success":
            True,

        "title":
            quiz_data.get(
                "title",
                topic + " Quiz"
            ),

        "topic":
            topic,

        "difficulty":
            difficulty,

        "questions":
            valid_questions

    })


# =========================================================
# SAVE QUIZ RESULT
# =========================================================

@app.route(
    "/save_quiz_result",
    methods=["POST"]
)
def save_quiz_result():

    if not is_logged_in():

        return jsonify({

            "success":
                False,

            "message":
                "Login required to save quiz history."

        })


    data = request.get_json()


    topic = data.get(
        "topic",
        "Unknown"
    )


    score = int(
        data.get(
            "score",
            0
        )
    )


    total = int(
        data.get(
            "total",
            0
        )
    )


    conn = get_db()


    conn.execute(
        """
        INSERT INTO quiz_results
        (user_id, topic, score, total)
        VALUES (?, ?, ?, ?)
        """,
        (
            session["user_id"],
            topic,
            score,
            total
        )
    )


    conn.commit()

    conn.close()


    return jsonify({
        "success":
            True
    })


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )