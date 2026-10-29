/* Aplica el tema antes del primer pintado para evitar el destello claro/oscuro. */
(function () {
  'use strict';
  try {
    var saved = localStorage.getItem('theme');
    var prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
    document.documentElement.setAttribute(
      'data-theme',
      saved === 'light' || (!saved && prefersLight) ? 'light' : 'dark'
    );
  } catch (error) {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
})();
