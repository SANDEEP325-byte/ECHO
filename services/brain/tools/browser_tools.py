"""ECHO Browser Tools (Phase 5C, 5D, 5E, 5F).

Provides concrete ECHO Tool implementations for safe browser automation:
- BrowserNavigateTool (browser_navigate)
- BrowserReadPageTool (browser_read_page)
- BrowserClickTool (browser_click)
- BrowserTypeTool (browser_type)
- BrowserDownloadTool (browser_download)
- BrowserUploadTool (browser_upload)

Integrates into the canonical ToolRegistry and ToolRouter pipeline.
"""

from typing import Any

from packages.interfaces.tool import Tool
from packages.interfaces.tool_schema import ToolDefinition, ToolParameter
from services.browser.operations import browser_operations
from services.browser.runner import browser_runner


class BrowserNavigateTool(Tool):
    """Tool to navigate to an authorized web URL using Playwright Chromium."""

    name = "browser_navigate"
    description = "Navigates to an authorized HTTP/HTTPS web URL using Playwright Chromium."

    definition = ToolDefinition(
        name="browser_navigate",
        description="Navigates to an authorized HTTP/HTTPS web URL using Playwright Chromium.",
        parameters=(
            ToolParameter(
                name="url",
                type="string",
                description="The target HTTP or HTTPS URL to navigate to.",
                required=True,
            ),
            ToolParameter(
                name="session_id",
                type="string",
                description="Optional browser session ID.",
                required=False,
            ),
        ),
    )

    def execute(  # type: ignore[override]
        self,
        url: str,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute navigation synchronously via the browser async runner."""
        return browser_runner.run(browser_operations.navigate(url=url, session_id=session_id))


class BrowserReadPageTool(Tool):
    """Tool to inspect and read text and metadata from the active browser webpage."""

    name = "browser_read_page"
    description = "Safely inspects and reads text and metadata from the active browser webpage."

    definition = ToolDefinition(
        name="browser_read_page",
        description="Safely inspects and reads text and metadata from the active browser webpage.",
        parameters=(
            ToolParameter(
                name="session_id",
                type="string",
                description="Optional browser session ID.",
                required=False,
            ),
            ToolParameter(
                name="max_length",
                type="integer",
                description="Maximum number of characters of page text to extract (default 10000).",
                required=False,
            ),
        ),
    )

    def execute(
        self,
        session_id: str | None = None,
        max_length: int = 10000,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute page inspection synchronously via the browser async runner."""
        return browser_runner.run(
            browser_operations.read_page(session_id=session_id, max_length=max_length)
        )


class BrowserClickTool(Tool):
    """Tool to click an element identified by selector on the active browser webpage."""

    name = "browser_click"
    description = "Clicks an element identified by selector on the active browser webpage."

    definition = ToolDefinition(
        name="browser_click",
        description="Clicks an element identified by selector on the active browser webpage.",
        parameters=(
            ToolParameter(
                name="selector",
                type="string",
                description="The CSS/text element selector to click.",
                required=True,
            ),
            ToolParameter(
                name="session_id",
                type="string",
                description="Optional browser session ID.",
                required=False,
            ),
            ToolParameter(
                name="is_submit",
                type="boolean",
                description="Whether this click triggers a form submission or state-changing action.",
                required=False,
            ),
        ),
    )

    def execute(  # type: ignore[override]
        self,
        selector: str,
        session_id: str | None = None,
        is_submit: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute element click synchronously via the browser async runner."""
        return browser_runner.run(
            browser_operations.click(
                selector=selector,
                session_id=session_id,
                is_submit=is_submit,
            )
        )


class BrowserTypeTool(Tool):
    """Tool to enter text into an input element identified by selector on the active browser webpage."""

    name = "browser_type"
    description = (
        "Enters text into an input element identified by selector on the active browser webpage."
    )

    definition = ToolDefinition(
        name="browser_type",
        description="Enters text into an input element identified by selector on the active browser webpage.",
        parameters=(
            ToolParameter(
                name="selector",
                type="string",
                description="The element selector to enter text into.",
                required=True,
            ),
            ToolParameter(
                name="text",
                type="string",
                description="The text to type into the input element.",
                required=True,
            ),
            ToolParameter(
                name="session_id",
                type="string",
                description="Optional browser session ID.",
                required=False,
            ),
            ToolParameter(
                name="is_sensitive",
                type="boolean",
                description="Whether the text contains sensitive credentials or secret information.",
                required=False,
            ),
            ToolParameter(
                name="submit",
                type="boolean",
                description="Whether to submit the form after typing by pressing Enter.",
                required=False,
            ),
        ),
    )

    def execute(  # type: ignore[override]
        self,
        selector: str,
        text: str,
        session_id: str | None = None,
        is_sensitive: bool = False,
        submit: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute controlled text input synchronously via the browser async runner."""
        return browser_runner.run(
            browser_operations.type_text(
                selector=selector,
                text=text,
                session_id=session_id,
                is_sensitive=is_sensitive,
                submit=submit,
            )
        )


browser_navigate_tool = BrowserNavigateTool()
browser_read_page_tool = BrowserReadPageTool()
browser_click_tool = BrowserClickTool()
browser_type_tool = BrowserTypeTool()


class BrowserDownloadTool(Tool):
    """Tool to securely download a file via URL or element click into an authorized sandbox location."""

    name = "browser_download"
    description = (
        "Downloads a file via URL navigation or element click into an authorized sandbox location."
    )

    definition = ToolDefinition(
        name="browser_download",
        description="Downloads a file via URL navigation or element click into an authorized sandbox location.",
        parameters=(
            ToolParameter(
                name="destination_path",
                type="string",
                description="The target file or directory path in an authorized sandbox location.",
                required=True,
            ),
            ToolParameter(
                name="url",
                type="string",
                description="Optional direct HTTP/HTTPS URL to download.",
                required=False,
            ),
            ToolParameter(
                name="selector",
                type="string",
                description="Optional element selector to click to trigger the download.",
                required=False,
            ),
            ToolParameter(
                name="session_id",
                type="string",
                description="Optional browser session ID.",
                required=False,
            ),
        ),
    )

    def execute(  # type: ignore[override]
        self,
        destination_path: str,
        url: str | None = None,
        selector: str | None = None,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute secure download synchronously via the browser async runner."""
        return browser_runner.run(
            browser_operations.download(
                destination_path=destination_path,
                url=url,
                selector=selector,
                session_id=session_id,
            )
        )


class BrowserUploadTool(Tool):
    """Tool to upload a local file from an authorized sandbox location into an element."""

    name = "browser_upload"
    description = "Uploads a local file from an authorized sandbox location into an input element."

    definition = ToolDefinition(
        name="browser_upload",
        description="Uploads a local file from an authorized sandbox location into an input element.",
        parameters=(
            ToolParameter(
                name="selector",
                type="string",
                description="The element selector targeting the file input.",
                required=True,
            ),
            ToolParameter(
                name="file_path",
                type="string",
                description="The local file path in an authorized sandbox location to upload.",
                required=True,
            ),
            ToolParameter(
                name="session_id",
                type="string",
                description="Optional browser session ID.",
                required=False,
            ),
        ),
    )

    def execute(  # type: ignore[override]
        self,
        selector: str,
        file_path: str,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Execute secure file upload synchronously via the browser async runner."""
        return browser_runner.run(
            browser_operations.upload(
                selector=selector,
                file_path=file_path,
                session_id=session_id,
            )
        )


browser_download_tool = BrowserDownloadTool()
browser_upload_tool = BrowserUploadTool()

ALL_BROWSER_TOOLS: list[Tool] = [
    browser_navigate_tool,
    browser_read_page_tool,
    browser_click_tool,
    browser_type_tool,
    browser_download_tool,
    browser_upload_tool,
]
