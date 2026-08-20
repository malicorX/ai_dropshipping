# Privacy policy — Dropship Desk

**Last updated:** 20 August 2026  
**Operator:** the person running this local application (see the GitHub account that hosts this repository).

This page describes how **Dropship Desk** handles data. The app runs on your own computer. It is not a public website and does not operate a consumer-facing cloud service.

## What this software is

Dropship Desk is a local Windows tool that helps evaluate Amazon.de products, draft eBay listings, and (when you enable it) talk to eBay APIs using **your** seller account.

## Data we do not collect

The software authors do **not** receive your product data, OAuth tokens, passwords, or listing content. There is no analytics backend in this repository.

## Data stored on your machine

Depending on how you use the app, files may be stored under a local `data/` folder (and related config such as `.env`), for example:

- product candidates (ASINs, titles, prices, listing drafts)
- downloaded product images
- eBay OAuth tokens after you connect your eBay account
- settings you enter in the app (margin rules, listing boilerplate)

You can delete that folder to remove local application data.

## eBay OAuth

If you click **Connect eBay**, the app opens eBay’s sign-in page and requests permission to use Sell APIs (for example inventory and account) on the eBay account you authorize.

- Access and refresh tokens are stored **only on your computer**.
- Tokens are used to call eBay APIs from your machine.
- You can revoke access in your eBay account / developer settings.

## Amazon

The app may load public Amazon.de search and product pages (and images) to evaluate offers. It does not send your Amazon password to the Dropship Desk authors. Any future Amazon cart/purchase automation is off unless you enable it in `.env`.

## Third parties

When you authorize eBay, **eBay** processes the sign-in and API traffic under eBay’s own policies. When the app fetches Amazon pages, **Amazon** sees ordinary web requests from your network.

A local language model (for example Ollama on your LAN) may receive product titles and related text to generate listing copy. That stays on the machines you configure.

## Your rights

Because data stays on your device, you control it: stop using the app, delete local files, and revoke eBay tokens.

## Contact

Questions about this policy: open an issue on this GitHub repository, or contact the operator through the eBay account that uses this software.
