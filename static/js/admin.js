/* Fighter Bull's admin — collapsible left-nav (accordion) + search box.
   Enhances Django's built-in #nav-sidebar: each app becomes a group whose
   models expand/collapse on click, and the existing filter is turned into a
   prominent search that auto-expands matching groups. */
(function () {
    function init() {
        var sidebar = document.getElementById("nav-sidebar");
        if (!sidebar) return;

        var modules = sidebar.querySelectorAll(".module");
        modules.forEach(function (mod) {
            var caption = mod.querySelector("caption");
            if (!caption) return;

            // Collapse everything except the app/model you're currently viewing.
            var isCurrent =
                mod.classList.contains("current-app") ||
                mod.querySelector(".current-model");
            if (!isCurrent) mod.classList.add("fb-collapsed");

            // Click the app header to expand/collapse its models (don't navigate).
            caption.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                mod.classList.toggle("fb-collapsed");
            });
        });

        // Turn Django's filter input into an obvious search; expand groups as
        // soon as the admin starts typing so matches aren't hidden by collapse.
        var filter = document.getElementById("nav-filter");
        if (filter) {
            filter.placeholder = "Search menu…";
            filter.setAttribute("aria-label", "Search admin menu");
            sidebar.classList.add("fb-has-search");
            var apply = function () {
                var searching = filter.value.trim().length > 0;
                sidebar.classList.toggle("fb-searching", searching);
                if (searching) {
                    modules.forEach(function (mod) {
                        mod.classList.remove("fb-collapsed");
                    });
                }
            };
            filter.addEventListener("input", apply);
        }
    }

    if (document.readyState !== "loading") init();
    else document.addEventListener("DOMContentLoaded", init);
})();
