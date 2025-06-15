
async function llmContentStreamer(
    url, // URL endpoint
    conversation_id, // Base ID of the content element
    queryType, // Query type for the llm
    targetElement,
    args,  // Are a string value of arguments with the format arg1=value1;arg2=value2
    id // ID of the container element
) {
    // Get csrf token from the cookie
    const csrfToken = getCookie("csrftoken");

    // Format the arguments
    var argsArray = args.split(";");
    var argsObject = {};
    argsArray.forEach((arg) => {
        var argArray = arg.split("=");
        argsObject[argArray[0]] = argArray[1];
    });

    // Get the input element
    var query = document.getElementById(`llm_query_${id}`).value;

    // If the query is empty, return
    if (query === "") {
        return;
    }

    // Create the user message
    bloomAiCreateMessage(query, true, id, queryType);

    // Create the assistance message
    var aiMessageId = bloomAiCreateMessage("", false, id, queryType);

    // Remove input value
    document.getElementById(`llm_query_${id}`).value = "";

    // Fetch the response from the server
    const response = await fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
            query: query,
            query_type: queryType,
            conversation_id: conversation_id,
            args: argsObject,
        })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let result = "";

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        result += decoder.decode(value, { stream: true });

        // Remove the ```html or ``` from the result, only when not bloom_ai
        if (!['bloom_ai','object_bloom_ai'].includes(queryType)) {
            result = result.replace("```html", "");
            result = result.replace("```", "");

            document.getElementById(aiMessageId).innerHTML = result;
        } else {
            // Markdown to HTML
            document.getElementById("md-" + aiMessageId).innerHTML = result;
        }

    }

}

function bloomAiCreateMessage(
    message, 
    isUser, 
    baseElementId, 
    queryType
) {
    // Generate a random message id
    var messageId = `message_${Math.floor(Math.random() * 1000000)}`;

    var messageContainer = document.createElement("div");
    messageContainer.className = "ai-message-container mb-2";

    // Wrapper
    var wrapper = document.createElement("div");
    wrapper.className = isUser ? "d-flex justify-content-end" : "d-flex justify-content-start";

    // Create bubble
    var messageBubble = document.createElement("div");
    messageBubble.id = messageId;

    messageBubble.className = isUser ? "user-bubble overflow-auto" : "assistant-bubble overflow-auto";

    // If the message is from the user, add the content
    if (isUser) {
        messageBubble.innerHTML = message;
    } else {
        // Add the spinner
        var spinner = createSpinner(false);
        messageBubble.appendChild(spinner);
    }

    if (message != "" && !['bloom_ai','object_bloom_ai'].includes(queryType)) {
        messageBubble.innerHTML = message;
    }

    // Append the message bubble to the wrapper
    wrapper.appendChild(messageBubble);
    messageContainer.appendChild(wrapper);

    // Add another div
    var utilsDiv = document.createElement("div");
    utilsDiv.className = isUser ? "d-flex justify-content-end mb-3 gap-2" : "d-flex justify-content-start mb-3 gap-2";

    // Add copy button
    var copyButton = document.createElement("a");
    copyButton.className = "bi bi-clipboard pointer";
    copyButton.title = "Copy to clipboard";
    copyButton.onclick = function () {
        navigator.clipboard.writeText(document.getElementById(messageId).innerText);
    }

    // Add insert to target button
    var insertButton = document.createElement("a");
    insertButton.className = "bi bi-arrow-down-circle pointer";
    insertButton.title = "Insert to target";
    var target = document.getElementById(`llm_output_${baseElementId}`);

    // Add the onclick event
    insertButton.onclick = function () {
        target.innerHTML = document.getElementById(messageId).innerHTML;
        target.dispatchEvent(new Event('llm-inserted'));
    }
    
    // Add data-bs-dismiss attribute
    insertButton.setAttribute("data-bs-dismiss", "modal");

    if (['bloom_ai','object_bloom_ai'].includes(queryType)) {
        // Add zero-md to the utils div
        let zeroMd = document.createElement("zero-md");
        let script = document.createElement("script");
        script.type = "text/markdown";
        script.id = "md-" + messageId;
        zeroMd.appendChild(script);

        if (!isUser) {
            // Add the markdown content to the script
            if (message != "") {
                script.innerHTML = message;
            }

            messageBubble.appendChild(zeroMd);
        }

        // Append the zero-md to the bubble
        messageBubble.appendChild(zeroMd);
    }

    // Append the copy button to the utils div
    if (!['bloom_ai','object_bloom_ai'].includes(queryType)) {
    utilsDiv.appendChild(insertButton);
    }
    utilsDiv.appendChild(copyButton);

    // Append the utils div to the message container
    messageContainer.appendChild(utilsDiv);

    // Append the message container to the conversation container
    document.getElementById(`conversation_container_${baseElementId}`).appendChild(messageContainer);

    return messageId;
}


function sendAiMessage(id, url) {
    // Get the conversation id
    var container = document.getElementById(`conversation_container_${id}`);

    var conversation_id = container.querySelector('#conversation_id').value;
    var query_type = container.querySelector('#query_type').value;
    var target = container.querySelector('#target').value;
    var args = container.querySelector('#args').value;

    // send the message to the llm
    llmContentStreamer(url, conversation_id, query_type, target, args, id);
}

