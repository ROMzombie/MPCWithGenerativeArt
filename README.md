# MPCWithGenerativeArt
Use the MakePlayingCards web interface and generative tools to create custom-appearing decks of cards

The primary interface should be a clean and simple web application that takes a file containing lines in this format:

Copies CardName (set) CollectorNumber\tprompt

Copies = Number of copies of the card to print
CardName = The name of the card
set = The set of the card
CollectorNumber = The collector number of the card
prompt = The prompt to use for generating the image

Example:
```
1 Byode, Inverse Sun (PH21) 3\tAn anime girl dressed like a pixie
1 All-Seeing Toby (SLD) 2695\tAn anime boy in a library holding a book
1 Animate Dead (SLD) 2189\tAn old man in an anime style holding his hand up with a magic sphere surroundning him
```

A submit button validates the file is in the correct format and then triggers the card generation process. 

For each card, the high-quality image will be retrieved from Scryfall, upscaled to 800 DPI, the "card art" replaced with a generated image based on the prompt and output as a png image.

The application will then show the images generated in a grid.

Under each image there should be a textbox and a submit button. The textbox should pre-populate with the prompt used to generate the image. The user can edit the prompt to change the image and then submit it to regenerate the image. 

When the user clicks the "I'm Done" link at the top of the page, the application will take all the generated images and upload them to the currently logged-in [makeplayingcards](https://www.makeplayingcards.com/) order.

This process should be similar to that provided by the mpc-autofill project https://github.com/chilli-axe/mpc-autofill.