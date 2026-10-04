const messageInput = document.getElementById("messageInput");

if (messageInput) {

    messageInput.addEventListener("input", function () {

        this.style.height = "auto";

        this.style.height =
            Math.min(this.scrollHeight, 150) + "px";

    });

    messageInput.addEventListener("keydown", function (event) {

        if (event.key === "Enter" && !event.shiftKey) {

            event.preventDefault();

            this.form.submit();

        }

    });
}


/* Scroll chat to bottom */

const messages = document.getElementById("messages");

if (messages) {
    messages.scrollTop = messages.scrollHeight;
}
