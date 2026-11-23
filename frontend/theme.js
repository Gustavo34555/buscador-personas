/* Aplica el tema antes del primer pintado para evitar el destello claro/oscuro. */
(function () {
  'use strict';
  try {
    var saved = localStorage.getItem('theme');
    var prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
    var theme = saved === 'light' || (!saved && prefersLight) ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme === 'light' ? '#f8fafc' : '#070709');
  } catch (error) {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
})();
