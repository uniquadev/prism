(function () {
  function enhanceResponsiveTables() {
    const tables = document.querySelectorAll(".md-typeset table:not([class])");

    tables.forEach(function (table) {
      if (table.dataset.responsiveTable === "true") {
        return;
      }

      const headers = Array.from(table.querySelectorAll("thead th")).map(function (header) {
        return header.textContent.trim();
      });

      if (!headers.length) {
        return;
      }

      table.dataset.responsiveTable = "true";

      table.querySelectorAll("tbody tr").forEach(function (row) {
        Array.from(row.children).forEach(function (cell, index) {
          if (headers[index]) {
            cell.setAttribute("data-label", headers[index]);
          }
        });
      });
    });
  }

  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(enhanceResponsiveTables);
  } else {
    document.addEventListener("DOMContentLoaded", enhanceResponsiveTables);
  }
})();
