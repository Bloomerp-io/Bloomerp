import type { BrowserDevice } from './definition';
import { TwilioDevice } from './twilio';
import { TelnyxDevice } from './telnyx';

/** Resolve only shipped SDK drivers selected by the server's provider definition. */
const drivers: Record<string, new (token: string) => BrowserDevice> = { twilio: TwilioDevice, telnyx: TelnyxDevice };

/** Construct a supported browser transport without assuming every provider uses Twilio. */
export function createBrowserDevice(driver: string, token: string): BrowserDevice {
    const Driver = Object.prototype.hasOwnProperty.call(drivers, driver) ? drivers[driver] : undefined;
    if (!Driver) throw new Error('Unsupported browser phone driver');
    return new Driver(token);
}
