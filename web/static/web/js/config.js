(function () {
    var host = window.location.hostname;
    var protocol = window.location.protocol === "https:" ? "https" : "http";

    // Universal API base URL for all frontend pages.
    // Change only here if backend host/port changes.
    var apiBaseUrl = host
        ? protocol + "://" + host + ":8000/api"
        : "http://127.0.0.1:8000/api";

    window.APP_CONFIG = Object.freeze({
        API_BASE_URL: apiBaseUrl
    });
})();
