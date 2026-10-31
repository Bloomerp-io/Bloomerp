import { MessageType } from "../components/UiMessage";
import { t } from "./i18n";
import showMessage from "./messages";

/** Copy a rendered value and report success only after the clipboard accepts it. */
export async function copyToClipboard(value: string): Promise<boolean> {
    try {
        await navigator.clipboard.writeText(value);
        showMessage(t("Copied to clipboard."), MessageType.SUCCESS);
        return true;
    } catch {
        showMessage(t("The value could not be copied to the clipboard."), MessageType.ERROR);
        return false;
    }
}
