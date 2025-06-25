document.addEventListener("DOMContentLoaded", function () {
    const getCookie = (name) => {
        let cookieValue = null;
        if (document.cookie && document.cookie !== "") {
            const cookies = document.cookie.split(";");
            for (let cookie of cookies) {
                cookie = cookie.trim();
                if (cookie.startsWith(name + "=")) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    };

    const loadNotifications = () => {
        fetch("/admin/notifications/fragment/")
            .then(response => response.text())
            .then(html => {
                const nav = document.querySelector("#jazzy-navbar .navbar-nav.ml-auto");
                let wrapper = document.querySelector("#admin-notifications-wrapper");

                if (!wrapper) {
                    wrapper = document.createElement("li");
                    wrapper.className = "nav-item dropdown";
                    wrapper.id = "admin-notifications-wrapper";
                    wrapper.innerHTML = `
                        <a class="nav-link" data-toggle="dropdown" href="#">
                            🔔 <span id="notification-badge" class="badge badge-warning"></span>
                        </a>
                        <div class="dropdown-menu dropdown-menu-lg dropdown-menu-right" id="admin-notifications-dropdown"></div>
                    `;
                    nav.prepend(wrapper);
                }

                // Update dropdown content
                const dropdown = wrapper.querySelector("#admin-notifications-dropdown");
                if (dropdown) {
                    dropdown.innerHTML = html;
                }

                // Update badge count
                const temp = document.createElement("div");
                temp.innerHTML = html;
                const unreadCountElement = temp.querySelector("#notification-unread-count");
                const unreadCount = unreadCountElement ? parseInt(unreadCountElement.dataset.count) : 0;

                const badge = document.getElementById("notification-badge");
                if (badge) {
                    badge.textContent = unreadCount > 0 ? unreadCount : "";
                    badge.style.display = unreadCount > 0 ? "inline-block" : "none";
                }
            });
    };

    // Mark notification as read and redirect
    document.addEventListener("click", function (e) {
        const link = e.target.closest(".dropdown-item");
        if (link && link.href && link.href.includes("/change/")) {
            e.preventDefault();
            const match = link.href.match(/\/(\d+)\/change\/$/);
            if (match) {
                fetch(`/admin/notifications/read/${match[1]}/`, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": getCookie("csrftoken"),
                        "Content-Type": "application/json"
                    },
                }).finally(() => {
                    window.location.href = link.href;
                });
            }
        }
    });

    loadNotifications();
    setInterval(loadNotifications, 5000);  // every 5s
});
