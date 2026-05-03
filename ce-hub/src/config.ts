function envFlag(name: string, defaultValue = false): boolean {
  const value = process.env[name];
  if (value === undefined || value === '') return defaultValue;
  return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase());
}

export const D68_CONFIG = {
  get SESSIONS(): boolean { return envFlag('CE_HUB_D68_SESSIONS'); },
  get QUARANTINE(): boolean { return envFlag('CE_HUB_D68_QUARANTINE'); },
  get ACKS(): boolean { return envFlag('CE_HUB_D68_ACKS'); },
  get INBOX_ROUTER(): boolean { return envFlag('CE_HUB_D68_INBOX_ROUTER'); },
  get RECOVERY_SUMMARY(): boolean { return envFlag('CE_HUB_D68_RECOVERY_SUMMARY'); },
  get GC(): boolean { return envFlag('CE_HUB_D68_GC'); },
};

export function d68PrAEnabled(): boolean {
  return D68_CONFIG.SESSIONS || D68_CONFIG.QUARANTINE || D68_CONFIG.ACKS;
}
