import {
  computed,
  createApp,
  reactive,
  ref,
} from "https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js";

const TOKEN_STORAGE_KEY = "redirect-manager-token";

createApp({
  setup() {
    const token = ref(localStorage.getItem(TOKEN_STORAGE_KEY) || "");
    const redirects = ref([]);
    const loading = ref(false);
    const saving = ref(false);
    const error = ref("");
    const success = ref("");

    const summary = computed(() => {
      const catchallCount = redirects.value.length;
      const ruleCount = redirects.value.reduce((count, redirect) => {
        return count + redirect.rules.length;
      }, 0);
      return `${catchallCount} destinations, ${ruleCount} rules`;
    });

    function authHeaders() {
      return token.value
        ? {
            Authorization: `Bearer ${token.value}`,
            "Content-Type": "application/json",
          }
        : { "Content-Type": "application/json" };
    }

    function clearMessages() {
      error.value = "";
      success.value = "";
    }

    async function loadRedirects() {
      clearMessages();
      loading.value = true;
      try {
        const response = await fetch("/api/redirects", {
          headers: authHeaders(),
        });
        if (!response.ok) {
          throw new Error(await readError(response));
        }
        const payload = await response.json();
        redirects.value = payload.redirects.map(cloneRedirect);
        localStorage.setItem(TOKEN_STORAGE_KEY, token.value);
      } catch (err) {
        error.value = err.message || "Failed to load redirects.";
      } finally {
        loading.value = false;
      }
    }

    async function saveRedirects() {
      clearMessages();
      saving.value = true;
      try {
        const response = await fetch("/api/redirects", {
          method: "PUT",
          headers: authHeaders(),
          body: JSON.stringify({
            redirects: redirects.value.map((redirect) => ({
              catchall_email: redirect.catchall_email.trim(),
              rules: redirect.rules.map((rule) => ({
                type: rule.type,
                value: rule.value.trim(),
              })),
            })),
          }),
        });
        if (!response.ok) {
          throw new Error(await readError(response));
        }
        const payload = await response.json();
        redirects.value = payload.redirects.map(cloneRedirect);
        localStorage.setItem(TOKEN_STORAGE_KEY, token.value);
        success.value = "Redirect settings saved.";
      } catch (err) {
        error.value = err.message || "Failed to save redirects.";
      } finally {
        saving.value = false;
      }
    }

    function addRedirect() {
      redirects.value.push(
        reactive({
          catchall_email: "",
          rules: [reactive({ type: "exact", value: "" })],
        }),
      );
    }

    function removeRedirect(index) {
      redirects.value.splice(index, 1);
    }

    function addRule(redirect) {
      redirect.rules.push(reactive({ type: "exact", value: "" }));
    }

    function removeRule(redirect, index) {
      redirect.rules.splice(index, 1);
    }

    return {
      addRedirect,
      addRule,
      error,
      loadRedirects,
      loading,
      redirects,
      removeRedirect,
      removeRule,
      saveRedirects,
      saving,
      success,
      summary,
      token,
    };
  },
  template: `
    <main class="shell">
      <section class="hero">
        <div>
          <p class="eyebrow">Watchdog Admin</p>
          <h1>Redirect Manager</h1>
          <p class="lede">Manage catchall delivery rules in <code>redirects_config.yaml</code>.</p>
        </div>
        <div class="summary-card">{{ summary }}</div>
      </section>

      <section class="panel auth-panel">
        <label class="field">
          <span>Web password</span>
          <input v-model="token" type="password" placeholder="Enter web.web_pwd from config.yaml">
        </label>
        <div class="auth-actions">
          <button class="secondary" @click="loadRedirects" :disabled="loading">Load</button>
          <button @click="saveRedirects" :disabled="saving">Save changes</button>
        </div>
        <p v-if="error" class="message error">{{ error }}</p>
        <p v-if="success" class="message success">{{ success }}</p>
      </section>

      <section class="panel">
        <div class="section-header">
          <div>
            <h2>Redirect destinations</h2>
            <p>Each destination gets exact-address and regex rules.</p>
          </div>
          <button @click="addRedirect">Add destination</button>
        </div>

        <div v-if="!redirects.length" class="empty-state">
          No redirect destinations yet. Add one to get started.
        </div>

        <article v-for="(redirect, redirectIndex) in redirects" :key="redirectIndex" class="redirect-card">
          <div class="redirect-header">
            <label class="field grow">
              <span>Catchall destination</span>
              <input v-model="redirect.catchall_email" type="email" placeholder="finance@example.com">
            </label>
            <button class="danger" @click="removeRedirect(redirectIndex)">Delete</button>
          </div>

          <div class="rules">
            <div v-for="(rule, ruleIndex) in redirect.rules" :key="ruleIndex" class="rule-row">
              <label class="field compact">
                <span>Type</span>
                <select v-model="rule.type">
                  <option value="exact">Exact</option>
                  <option value="regex">Regex</option>
                </select>
              </label>
              <label class="field grow">
                <span>Value</span>
                <input
                  v-model="rule.value"
                  type="text"
                  :placeholder="rule.type === 'regex' ? '^invoice-.*$' : 'accounts'"
                >
              </label>
              <button class="ghost" @click="removeRule(redirect, ruleIndex)">Remove</button>
            </div>
          </div>

          <button class="secondary" @click="addRule(redirect)">Add rule</button>
        </article>
      </section>
    </main>
  `,
}).mount("#app");

function cloneRedirect(redirect) {
  return reactive({
    catchall_email: redirect.catchall_email || "",
    rules: Array.isArray(redirect.rules)
      ? redirect.rules.map((rule) =>
          reactive({
            type: rule.type || "exact",
            value: rule.value || "",
          }),
        )
      : [],
  });
}

async function readError(response) {
  try {
    const payload = await response.json();
    return payload.error || payload.reason || response.statusText;
  } catch {
    return response.statusText;
  }
}
