function setM2MValue(pk, displayText, widgetName) {
  // Get the display id for the widget
  input_div = document.getElementById(`${widgetName}_input_div`);

  // Create a new input element if it doesn't exist
  if (document.getElementById(`${widgetName}_${pk}`) == null) {
    let newInput = document.createElement("input");
    newInput.setAttribute("value", pk);
    newInput.id = `${widgetName}_${pk}`;
    newInput.name = widgetName;
    input_div.appendChild(newInput);

    // Create a new span element to display the selected object
    view_div = document.getElementById(`${widgetName}_view_div`);
    let newSpan = document.createElement("span");
    newSpan.className = "badge label-span";
    newSpan.id = `${widgetName}_span_${pk}`;
    newSpan.innerHTML = displayText;
    newSpan.onclick = function () {
      removeM2M(widgetName, pk);
    };
    view_div.appendChild(newSpan);
  }
}

function removeM2M(widgetName, pk) {
  // Get the input and view divs for the widget
  let input_div = document.getElementById(`${widgetName}_input_div`);
  let hiddenInput = document.getElementById(`${widgetName}_${pk}`);
  let view_div = document.getElementById(`${widgetName}_view_div`);

  // Remove the hidden input element for the selected item
  if (hiddenInput) {
    input_div.removeChild(hiddenInput);
  }

  // Find the correct span element to remove
  let spanToRemove = document.getElementById(`${widgetName}_span_${pk}`);
  if (spanToRemove) {
    view_div.removeChild(spanToRemove);
  }
}

function setForeignKeyValue(pk, displayText, widgetName) {
  // Set the hidden input value to the selected object's pk
  let hiddenInputId = widgetName + "_hidden_input";
  let hiddenInput = document.getElementById(hiddenInputId);

  hiddenInput.setAttribute("value", pk);

  console.log("Updating input");

  // Update the non-hidden input to show the selected item's display text
  let widgetDisplayId = widgetName + "_display";
  document.getElementById(widgetDisplayId).value = displayText;

  // Update the view div to show the selected item
  let view_div = document.getElementById(widgetName + "_view_div");
  view_div.querySelector("span").innerHTML = displayText;
}

function setNewObject(widgetName, elementId, widgetType) {
    // Search for the hidden input element inside of the element
    let element = document.getElementById(elementId);

    if (element == null) {
      return;
    }

    let objectId = element.getAttribute("data-object-id");
    let objectDisplayText = element.getAttribute("data-display-text");  

    if (widgetType == "m2m") {
      setM2MValue(objectId, objectDisplayText, widgetName);
    }
    else if (widgetType == "fk") {
      setForeignKeyValue(objectId, objectDisplayText, widgetName);
    }
}


function removeForeignKey(widgetName) {
  // Get the hidden input
  hiddenInputId = widgetName + "_hidden_input";
  let hiddenInput = document.getElementById(hiddenInputId);

  // Clear the hidden input
  hiddenInput.setAttribute("value", "");

  // Clear the display input
  let widgetDisplayId = widgetName + "_display";
  document.getElementById(widgetDisplayId).value = "";

  // Clear the view div
  let view_div = document.getElementById(widgetName + "_view_div");
  view_div.querySelector("span").innerHTML = "";
}


function addClickableEventListener(widgetName, widgetType) {
  // Get all of the advanced search divs
  // An advanced search div has the id of widgetName_advanced_search
  console.log("Adding event listener for " + widgetName + " with type " + widgetType);


  let div = document.getElementById(widgetName + "_advanced_search_table");

  document.addEventListener("htmx:afterSwap", function (event) {
    
    if (event.target.id.startsWith("datatable")) {
      // Get target id
      console.log("Event target id: " + event.target.id);

      let targetId = event.target.id;

      // Check if the target id is in the advanced search div
      table = document.getElementById(targetId).querySelector("tbody");

      if (table == null) {
        return;
      }

      // Add event listener to the rows
      let rows = table.querySelectorAll("tr");
      rows.forEach((row) => {
        row.classList.add("pointer");

        // Check if row already has an event listener
        if (row.getAttribute("data-clickable") == "true") {
          return;
        }

        // Check if row already has an event listener
        if (row.getAttribute("data-clickable") == "true") {
          return;
        }

        row.addEventListener("click", function () {
          // Add data clickable attribute to row
          row.setAttribute("data-clickable", "true");

          let pk = row.getAttribute("data-id");
          let displayText = row.getAttribute("data-display-text");

          if (widgetType == "m2m") {
            setM2MValue(pk, displayText, widgetName);
          } else if (widgetType == "fk") {
            setForeignKeyValue(pk, displayText, widgetName);
          }

          // Show message
          showMessage("Selected " + displayText + " with pk " + pk, "info");
        });
      });
    }
  });
}



// Add a single delegated event listener to handle all .showmodal clicks
document.body.addEventListener("click", function (event) {
    if (event.target.classList.contains("showmodal")) {
        event.preventDefault();
        const modalId = event.target.getAttribute("data-show-modal");
        if (modalId) {
            showModal(modalId);
        }
    }
});

document.body.addEventListener("hidden.bs.modal", () => {
	// If all the modals are closed, remove the backdrop
	
	// Get all the modals
	let modals = document.getElementsByClassName("modal");

	// Check if a modal has the show class
	let hasShow = false;
	for (let i = 0; i < modals.length; i++) {
		if (modals[i].classList.contains("show")) {
			hasShow = true;
			break;
		}
	}

	// Remove the backdrop if no modal has the show class
	if (!hasShow) {
		let backdrop = document.querySelector(".modal-backdrop");
		if (backdrop) {
			backdrop.remove();
		}
	}

	// Remove the style attribute from the body
	document.body.removeAttribute("style");
  });


function showModal(modal) {
    const mid = document.getElementById(modal);
    let myModal = new bootstrap.Modal(mid);
    myModal.show();
  }