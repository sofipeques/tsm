from __future__ import annotations
import requests, time, os, re
from TSRUrl import TSRUrl
from logger import logger
from exceptions import *

# Tiempo mínimo que el servidor requiere entre initDownload y getdownloadurl.
# El browser muestra 4s de countdown — usamos 5s para tener margen.
TICKET_WAIT_SECONDS = 4

def stripForbiddenCharacters(string: str) -> str:
    return re.sub('[\\<>/:"|?*]', "", string)


class TSRDownload:
    @classmethod
    def __init__(self, url: TSRUrl, sessionId: str):
        self.session: requests.Session = requests.Session()
        self.session.cookies.set(
            "tsrdlsession", sessionId,
            domain=".thesimsresource.com",
            path="/"
        )
        self.url: TSRUrl = url
        self.ticket: str = ""
        self.ticket_time: float = 0.0
        self.__getTSRDLTicketCookie()

    @classmethod
    def download(self, downloadPath: str) -> str:
        logger.info(f"Starting download for: {self.url.url}")

        downloadUrl = self.__getDownloadUrl()
        logger.debug(f"Got downloadUrl: {downloadUrl}")
        fileName = stripForbiddenCharacters(self.__getFileName(downloadUrl))
        logger.debug(f"Got fileName: {fileName}")

        startingBytes = (
            os.path.getsize(f"{downloadPath}/{fileName}.part")
            if os.path.exists(f"{downloadPath}/{fileName}.part")
            else 0
        )
        logger.debug(f"Got startingBytes: {startingBytes}")
        request = self.session.get(
            downloadUrl,
            stream=True,
            headers={"Range": f"bytes={startingBytes}-"},
        )
        logger.debug(f"Request status is: {request.status_code}")
        file = open(f"{downloadPath}/{fileName}.part", "wb")

        for index, chunk in enumerate(request.iter_content(1024 * 128)):
            logger.debug(f"Downloading chunk #{index} of {downloadUrl}")
            file.write(chunk)
        file.close()
        logger.debug(f"Removing .part from file name: {fileName}")
        if os.path.exists(f"{downloadPath}/{fileName}"):
            logger.debug(f"{downloadPath}/{fileName} Already exists! Replacing file")
            os.replace(f"{downloadPath}/{fileName}.part", f"{downloadPath}/{fileName}")
        else:
            logger.debug(f"{downloadPath}/{fileName} doesn't exist! Renaming file")
            os.rename(
                f"{downloadPath}/{fileName}.part",
                f"{downloadPath}/{fileName}",
            )
        return fileName

    @classmethod
    def __getFileName(self, downloadUrl: str) -> str:
        return re.search(
            r'(?<=filename=").+(?=")',
            requests.get(downloadUrl, stream=True).headers["Content-Disposition"],
        )[0]

    @classmethod
    def __getDownloadUrl(self) -> str:
        # Esperar el tiempo mínimo que el servidor requiere desde que se generó el ticket
        elapsed = time.time() - self.ticket_time
        remaining = TICKET_WAIT_SECONDS - elapsed
        if remaining > 0:
            logger.debug(f"Waiting {remaining:.1f}s for ticket to become valid server-side...")
            time.sleep(remaining)

        url = (
            f"https://www.thesimsresource.com/ajax.php"
            f"?c=downloads&a=getdownloadurl&ajax=1"
            f"&itemid={self.url.itemId}&mid=0&lk=0"
            f"&ticket={self.ticket}"
        )
        logger.debug(f"Calling getdownloadurl: {url}")

        response = self.session.get(url)
        logger.debug(f"getdownloadurl response: {response.text}")

        responseJSON = response.json()
        error = responseJSON.get("error", "")

        if response.status_code == 200:
            if not error:
                return responseJSON["url"]
            elif error == "Invalid download ticket":
                raise InvalidDownloadTicket(response.url, self.session.cookies)
            else:
                raise Exception(f"getdownloadurl error: {repr(error)}")
        else:
            raise requests.exceptions.HTTPError(response)

    @classmethod
    def __getTSRDLTicketCookie(self):
        logger.info(f"Getting 'tsrdlticket' cookie for: {self.url.url}")

        response = self.session.get(
            f"https://www.thesimsresource.com/ajax.php"
            f"?c=downloads&a=initDownload"
            f"&itemid={self.url.itemId}&setItems=&format=zip"
        )
        data = response.json()

        if data.get("error", ""):
            raise Exception(f"initDownload error: {data['error']}")

        redirect_url = data.get("url", "")
        ticket_match = re.search(r"/ticket/([^/]+?)/?$", redirect_url)
        if ticket_match:
            self.ticket = ticket_match.group(1)
            logger.debug(f"Got ticket: {self.ticket}")
        else:
            raise Exception(f"No se pudo extraer ticket de: {redirect_url}")

        tsrdlticket = response.cookies.get("tsrdlticket") or self.session.cookies.get("tsrdlticket")
        if tsrdlticket:
            self.session.cookies.set(
                "tsrdlticket", tsrdlticket,
                domain=".thesimsresource.com",
                path="/"
            )

        wait_page = f"https://www.thesimsresource.com{redirect_url}"
        logger.debug(f"Visiting wait page: {wait_page}")
        wait_resp = self.session.get(wait_page, allow_redirects=True)

        # Guardar el tiempo DESPUÉS de visitar la wait page — el servidor
        # empieza a contar desde que recibe esa visita
        self.ticket_time = time.time()

        new_session = wait_resp.cookies.get("tsrdlsession")
        if new_session:
            self.session.cookies.set(
                "tsrdlsession", new_session,
                domain=".thesimsresource.com",
                path="/"
            )
            logger.debug(f"Updated tsrdlsession: {new_session}")