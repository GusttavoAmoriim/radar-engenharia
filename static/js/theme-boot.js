// Runs before first paint (classic script): apply the saved theme to avoid a flash.
(function () {
  try {
    var key = 'radar.theme';
    var value = localStorage.getItem(key);
    if (!value) {
      var legacy = localStorage.getItem('speedlora.colorScheme.v2');
      if (legacy) {
        value = legacy === 'speedlora' ? 'dark' : 'light';
        localStorage.setItem(key, value);
      }
    }
    if (value === 'light' || value === 'dark') document.documentElement.dataset.theme = value;
  } catch (e) {
    /* storage blocked: follow the system theme */
  }
})();
