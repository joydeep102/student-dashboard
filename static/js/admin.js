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

    function initCharts() {
        var el = document.getElementById("fb-chart-data");
        if (!el || typeof Chart === "undefined") return;
        var d;
        try { d = JSON.parse(el.textContent); } catch (e) { return; }

        Chart.defaults.font.family =
            "'Segoe UI', system-ui, -apple-system, sans-serif";
        Chart.defaults.color = "#6b7280";

        var enroll = document.getElementById("chEnroll");
        if (enroll && d.enroll_counts) {
            var ctx = enroll.getContext("2d");
            var grad = ctx.createLinearGradient(0, 0, 0, 240);
            grad.addColorStop(0, "rgba(25,176,54,.28)");
            grad.addColorStop(1, "rgba(25,176,54,0)");
            new Chart(enroll, {
                type: "line",
                data: {
                    labels: d.enroll_labels,
                    datasets: [{
                        data: d.enroll_counts,
                        borderColor: "#19b036",
                        backgroundColor: grad,
                        borderWidth: 3,
                        fill: true,
                        tension: 0.4,
                        pointBackgroundColor: "#19b036",
                        pointRadius: 4,
                        pointHoverRadius: 6,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, ticks: { precision: 0 },
                             grid: { color: "#eef1f6" } },
                        x: { grid: { display: false } },
                    },
                },
            });
        }

        var plan = document.getElementById("chPlan");
        if (plan && d.plan_counts && d.plan_counts.length) {
            new Chart(plan, {
                type: "doughnut",
                data: {
                    labels: d.plan_labels,
                    datasets: [{
                        data: d.plan_counts,
                        backgroundColor: ["#19b036", "#4cc466", "#a3e635", "#0a7d20", "#7cb305", "#16a34a"],
                        borderWidth: 0,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: "62%",
                    plugins: { legend: { position: "right", labels: { boxWidth: 12, padding: 14 } } },
                },
            });
        }
    }

    function boot() { init(); initCharts(); }
    if (document.readyState !== "loading") boot();
    else document.addEventListener("DOMContentLoaded", boot);
})();
