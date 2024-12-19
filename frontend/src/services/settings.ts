export const LATEST_SETTINGS_VERSION = 4;

export type Settings = {
  LLM_MODEL: string;
  LLM_BASE_URL: string;
  AGENT: string;
  LANGUAGE: string;
  LLM_API_KEY: string | null;
  CONFIRMATION_MODE: boolean;
  SECURITY_ANALYZER: string;
};

export const DEFAULT_SETTINGS: Settings = {
  LLM_MODEL: "anthropic/claude-3-5-sonnet-20241022",
  LLM_BASE_URL: "",
  AGENT: "CodeActAgent",
  LANGUAGE: "en",
  LLM_API_KEY: null,
  CONFIRMATION_MODE: false,
  SECURITY_ANALYZER: "",
};

const validKeys = Object.keys(DEFAULT_SETTINGS) as (keyof Settings)[];

export const getCurrentSettingsVersion = () => {
  const settingsVersion = localStorage.getItem("SETTINGS_VERSION");
  if (!settingsVersion) return 0;
  try {
    return parseInt(settingsVersion, 10);
  } catch (e) {
    return 0;
  }
};

export const settingsAreUpToDate = () =>
  getCurrentSettingsVersion() === LATEST_SETTINGS_VERSION;

export const maybeMigrateSettings = (logout: () => void) => {
  // Sometimes we ship major changes, like a new default agent.
  // In this case, we may want to override a previous choice made by the user.
  const currentVersion = getCurrentSettingsVersion();

  if (currentVersion < 1) {
    localStorage.setItem("AGENT", DEFAULT_SETTINGS.AGENT);
  }
  if (currentVersion < 2) {
    const customModel = localStorage.getItem("CUSTOM_LLM_MODEL");
    if (customModel) {
      localStorage.setItem("LLM_MODEL", customModel);
    }
    localStorage.removeItem("CUSTOM_LLM_MODEL");
    localStorage.removeItem("USING_CUSTOM_MODEL");
  }
  if (currentVersion < 3) {
    localStorage.removeItem("token");
  }

  if (currentVersion < 4) {
    logout();
  }
};

/**
 * Get the default settings
 */
export const getDefaultSettings = (): Settings => DEFAULT_SETTINGS;

/**
 * Get the settings from the server or use the default settings if not found
 */
export const getSettings = async (): Promise<Settings> => {
  try {
    const response = await fetch("/api/settings");
    if (!response.ok) {
      throw new Error("Failed to load settings");
    }
    const settings = await response.json();
    if (settings != null) {
      return {
        ...DEFAULT_SETTINGS,
        ...settings,
      };
    }
  } catch (error) {
    console.error("Error loading settings:", error);
    return DEFAULT_SETTINGS;
  }
  const model = localStorage.getItem("LLM_MODEL");
  const baseUrl = localStorage.getItem("LLM_BASE_URL");
  const agent = localStorage.getItem("AGENT");
  const language = localStorage.getItem("LANGUAGE");
  const apiKey = localStorage.getItem("LLM_API_KEY");
  const confirmationMode = localStorage.getItem("CONFIRMATION_MODE") === "true";
  const securityAnalyzer = localStorage.getItem("SECURITY_ANALYZER");

  return {
    LLM_MODEL: model || DEFAULT_SETTINGS.LLM_MODEL,
    LLM_BASE_URL: baseUrl || DEFAULT_SETTINGS.LLM_BASE_URL,
    AGENT: agent || DEFAULT_SETTINGS.AGENT,
    LANGUAGE: language || DEFAULT_SETTINGS.LANGUAGE,
    LLM_API_KEY: apiKey || DEFAULT_SETTINGS.LLM_API_KEY,
    CONFIRMATION_MODE: confirmationMode || DEFAULT_SETTINGS.CONFIRMATION_MODE,
    SECURITY_ANALYZER: securityAnalyzer || DEFAULT_SETTINGS.SECURITY_ANALYZER,
  };
};

/**
 * Save the settings to the server. Only valid settings are saved.
 * @param settings - the settings to save
 */
export const saveSettings = async (
  settings: Partial<Settings>
): Promise<boolean> => {
  try {
    // Filter out invalid keys
    const validSettings = Object.fromEntries(
      Object.entries(settings).filter(([key]) =>
        validKeys.includes(key as keyof Settings),
      ),
    );

    // Clean up values
    Object.entries(validSettings).forEach(([key, value]) => {
      if (value === undefined || value === null) {
        validSettings[key] = "";
      } else if (typeof value === "string") {
        validSettings[key] = value.trim();
      }
    });

    // Get current settings to preserve API key if not provided
    const currentSettings = await getSettings();

    const response = await fetch("/api/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...currentSettings,
        ...validSettings,
      }),
    });

    if (!response.ok) {
      throw new Error("Failed to save settings");
    }

    return await response.json();
  } catch (error) {
    console.error("Error saving settings:", error);
    return false;
  }
};
