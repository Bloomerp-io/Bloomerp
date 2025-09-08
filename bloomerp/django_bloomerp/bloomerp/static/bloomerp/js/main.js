/**
 * Template Name: NiceAdmin - v2.2.2
 * Template URL: https://bootstrapmade.com/nice-admin-bootstrap-admin-html-template/
 * Author: BootstrapMade.com
 * License: https://bootstrapmade.com/license/
 */
(function () {
    "use strict";
    /**
     * Easy selector helper function
     */
    const select = (el, all = false) => {
        el = el.trim();
        if (all) {
            return [...document.querySelectorAll(el)];
        } else {
            return document.querySelector(el);
        }
    };

    /**
     * Easy event listener function
     */
    const on = (type, el, listener, all = false) => {
        if (all) {
            select(el, all).forEach((e) => e.addEventListener(type, listener));
        } else {
            select(el, all).addEventListener(type, listener);
        }
    };

    /**
     * Easy on scroll event listener
     */
    const onscroll = (el, listener) => {
        el.addEventListener("scroll", listener);
    };

    /**
     * Sidebar toggle
     */
    if (select(".toggle-sidebar-btn")) {
        on("click", ".toggle-sidebar-btn", function (e) {
            select("body").classList.toggle("toggle-sidebar");
        });
    }

    /**
     * Search bar toggle
     */
    if (select(".search-bar-toggle")) {
        on("click", ".search-bar-toggle", function (e) {
            select(".search-bar").classList.toggle("search-bar-show");
        });
    }

    /**
     * Navbar links active state on scroll
     */
    let navbarlinks = select("#navbar .scrollto", true);
    const navbarlinksActive = () => {
        let position = window.scrollY + 200;
        navbarlinks.forEach((navbarlink) => {
            if (!navbarlink.hash) return;
            let section = select(navbarlink.hash);
            if (!section) return;
            if (
                position >= section.offsetTop &&
                position <= section.offsetTop + section.offsetHeight
            ) {
                navbarlink.classList.add("active");
            } else {
                navbarlink.classList.remove("active");
            }
        });
    };
    window.addEventListener("load", navbarlinksActive);
    onscroll(document, navbarlinksActive);

    /**
     * Toggle .header-scrolled class to #header when page is scrolled
     */
    let selectHeader = select("#header");
    if (selectHeader) {
        const headerScrolled = () => {
            if (window.scrollY > 100) {
                selectHeader.classList.add("header-scrolled");
            } else {
                selectHeader.classList.remove("header-scrolled");
            }
        };
        window.addEventListener("load", headerScrolled);
        onscroll(document, headerScrolled);
    }

    /**
     * Back to top button
     */
    let backtotop = select(".back-to-top");
    if (backtotop) {
        const toggleBacktotop = () => {
            if (window.scrollY > 100) {
                backtotop.classList.add("active");
            } else {
                backtotop.classList.remove("active");
            }
        };
        window.addEventListener("load", toggleBacktotop);
        onscroll(document, toggleBacktotop);
    }

    /**
     * Initiate tooltips
     */
    var tooltipTriggerList = [].slice.call(
        document.querySelectorAll('[data-bs-toggle="tooltip"]')
    );
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    /**
     * Initiate Bootstrap validation check
     */
    var needsValidation = document.querySelectorAll(".needs-validation");

    Array.prototype.slice.call(needsValidation).forEach(function (form) {
        form.addEventListener(
            "submit",
            function (event) {
                if (!form.checkValidity()) {
                    event.preventDefault();
                    event.stopPropagation();
                }

                form.classList.add("was-validated");
            },
            false
        );
    });

    /**
     * Initiate Datatables
     */
    const datatables = select(".datatable", true);
    datatables.forEach((datatable) => {
        new simpleDatatables.DataTable(datatable);
    });
})();

// --------------------------------------------
// Functions to get cookies
// --------------------------------------------
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== "") {
        const cookies = document.cookie.split(";");
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === name + "=") {
                cookieValue = decodeURIComponent(
                    cookie.substring(name.length + 1)
                );
                break;
            }
        }
    }
    return cookieValue;
}

// --------------------------------------------
// Functions to toggle sidebar
// --------------------------------------------
function toggleBloomerpSidebar() {
    document.body.classList.toggle("toggle-sidebar");
}

function hideBloomerpSidebar() {
    document.body.classList.add("toggle-sidebar");
}

function showBloomerpSidebar() {
    document.body.classList.remove("toggle-sidebar");
}

// --------------------------------------------
// HTMX Indicator
// --------------------------------------------
function createSpinner(addContainer = true) {
    const spinner = document.createElement("div");
    spinner.id = "spinner";
    if (addContainer) spinner.className = "spinner-container";

    const spinnerBorder = document.createElement("div");
    spinnerBorder.className = addContainer ? "spinner-border" : "";
    spinnerBorder.setAttribute("role", "status");

    const spinnerText = document.createElement("span");
    spinnerText.className = "visually-hidden";
    spinnerText.innerText = "Loading...";

    spinnerBorder.appendChild(spinnerText);
    spinner.appendChild(spinnerBorder);

    return spinner;
}

document.addEventListener("htmx:beforeRequest", function (event) {
    var target = event.detail.target;

    if (target.id === "main-content" || target.id === "detail-content") {

    target.parentElement.insertBefore(createSpinner(), target);

    // Hide the target element
    target.style.visibility = "hidden";
    }
});


document.addEventListener("htmx:beforeHistorySave", async function(event) {
    // Remove the spinner
    var spinner = document.getElementById("spinner");
    if (spinner) {
        spinner.remove();
    }
});

document.addEventListener("htmx:afterRequest", function (event) {
    var xhr = event.detail.xhr;
    // Show the target element
    var target = event.detail.target;
    target.style.visibility = "visible";
    // Make the target element visible
    if (xhr.status === 500) {
        target.innerHTML = "<p>Oops, something went wrong.</p>";
    }
    
});


/**
 * Modal functions
 */

function toggleFullScreenModal(modalDialogId) {
    var modalDialog = document.getElementById(modalDialogId);
    modalDialog.classList.toggle("modal-fullscreen");
}