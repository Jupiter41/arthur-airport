"""Embed the captioned demo in slide 13 as an in-page PDF video annotation.

Run after `typst compile slides.typ slides.pdf`. Uses PDF 1.7 Adobe extension
level 3 RichMedia dictionaries with a native H.264 /Video asset, without Flash,
JavaScript, launch actions or external URLs. Playback requires a PDF viewer
that implements RichMedia video (for example desktop Acrobat/Reader).
"""

import hashlib
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    ByteStringObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


ROOT = Path(__file__).resolve().parent


def dictionary(**entries: object) -> DictionaryObject:
    return DictionaryObject({NameObject('/' + key): value for key, value in entries.items()})


def name(value: str) -> NameObject:
    return NameObject('/' + value)


def main() -> None:
    path = ROOT / 'slides.pdf'
    video = (ROOT / 'demo.mp4').read_bytes()
    reader = PdfReader(path)
    assert len(reader.pages) == 20
    assert 'The twin, running' in reader.pages[12].extract_text()
    if any(annotation.get_object().get('/Subtype') == '/RichMedia'
           for annotation in reader.pages[12].get('/Annots', [])):
        raise SystemExit('The PDF already contains a video. Recompile slides.typ first.')

    writer = PdfWriter(clone_from=reader)
    page = writer.pages[12]
    # Remove the previous external movie link when processing an older export.
    page[NameObject('/Annots')] = ArrayObject([
        annotation for annotation in page.get('/Annots', [])
        if annotation.get_object().get('/A', {}).get('/URI') != 'demo.mp4'
    ])

    embedded = DecodedStreamObject()
    embedded.set_data(video)
    embedded.update(dictionary(
        Type=name('EmbeddedFile'), Subtype=name('video/mp4'),
        Params=dictionary(Size=NumberObject(len(video)),
                          CheckSum=ByteStringObject(hashlib.md5(video).digest())),
    ))
    embedded_ref = writer._add_object(embedded)
    file_spec = writer._add_object(dictionary(
        Type=name('Filespec'), F=TextStringObject('demo.mp4'),
        UF=TextStringObject('demo.mp4'),
        Desc=TextStringObject('46-second airport demonstration with English subtitles'),
        EF=dictionary(F=embedded_ref, UF=embedded_ref),
    ))
    instance = writer._add_object(dictionary(
        Type=name('RichMediaInstance'), Subtype=name('Video'), Asset=file_spec,
    ))
    configuration = writer._add_object(dictionary(
        Type=name('RichMediaConfiguration'), Subtype=name('Video'),
        Name=TextStringObject('Airport demonstration'), Instances=ArrayObject([instance]),
    ))
    content = writer._add_object(dictionary(
        Type=name('RichMediaContent'),
        Assets=dictionary(Names=ArrayObject([TextStringObject('demo.mp4'), file_spec])),
        Configurations=ArrayObject([configuration]),
    ))
    settings = writer._add_object(dictionary(
        Type=name('RichMediaSettings'),
        Activation=dictionary(
            Type=name('RichMediaActivation'), Condition=name('XA'),
            Configuration=configuration,
            Presentation=dictionary(
                Type=name('RichMediaPresentation'), Style=name('Embedded'),
                Toolbar=BooleanObject(True), NavigationPane=BooleanObject(False),
                Transparent=BooleanObject(False), PassContextClick=BooleanObject(True),
            ),
        ),
        Deactivation=dictionary(Type=name('RichMediaDeactivation'), Condition=name('PI')),
    ))

    # The 16:9 poster is centered in the slide's 1160 x 480 pt dark frame.
    width, height = 480 * 16 / 9, 480
    left, bottom = 60 + (1160 - width) / 2, 80
    posters = [(key, value) for key, value in page['/Resources']['/XObject'].items()
               if value.get_object().get('/Subtype') == '/Image'
               and value.get_object().get('/Width') == 1920
               and value.get_object().get('/Height') == 1080]
    assert len(posters) == 1, 'Cannot identify the original video poster'
    appearance = DecodedStreamObject()
    appearance.set_data(f'q {width:.8f} 0 0 {height} 0 0 cm /Poster Do Q'.encode())
    appearance.update(dictionary(
        Type=name('XObject'), Subtype=name('Form'), FormType=NumberObject(1),
        BBox=ArrayObject([FloatObject(v) for v in (0, 0, width, height)]),
        Resources=dictionary(XObject=dictionary(Poster=posters[0][1])),
    ))
    annotation = dictionary(
        Type=name('Annot'), Subtype=name('RichMedia'),
        Rect=ArrayObject([FloatObject(v) for v in (left, bottom, left + width, bottom + height)]),
        NM=TextStringObject('EVSK-captioned-demo'),
        Contents=TextStringObject('Play the captioned airport demo within this page'),
        F=NumberObject(4), Border=ArrayObject([NumberObject(0)] * 3),
        AP=dictionary(N=writer._add_object(appearance)),
        RichMediaContent=content, RichMediaSettings=settings,
    )
    writer.add_annotation(12, annotation)
    # Also expose the same embedded stream in the viewer's attachments panel.
    catalog = writer._root_object
    names = catalog.get('/Names', DictionaryObject()).get_object()
    assert '/EmbeddedFiles' not in names, 'Compile a fresh PDF before embedding'
    names[NameObject('/EmbeddedFiles')] = writer._add_object(dictionary(
        Names=ArrayObject([TextStringObject('demo.mp4'), file_spec]),
    ))
    catalog[NameObject('/Names')] = names
    catalog[NameObject('/Extensions')] = dictionary(
        ADBE=dictionary(BaseVersion=name('1.7'), ExtensionLevel=NumberObject(3)),
    )
    temporary = path.with_suffix('.embedded.tmp.pdf')
    writer.write(temporary)

    # Verify the file's self-contained media graph before replacing the export.
    check = PdfReader(temporary)
    media = [a.get_object() for a in check.pages[12]['/Annots']
             if a.get_object().get('/Subtype') == '/RichMedia']
    assert len(media) == 1
    assert len(check.pages) == len(reader.pages)
    annotation = media[0]
    activation = annotation['/RichMediaSettings']['/Activation']
    assert activation['/Presentation']['/Style'] == '/Embedded'
    asset = annotation['/RichMediaContent']['/Configurations'][0].get_object()['/Instances'][0].get_object()['/Asset']
    assert asset['/EF']['/F'].get_data() == video
    assert check.attachments['demo.mp4'][0] == video
    assert not any(a.get_object().get('/A', {}).get('/URI') == 'demo.mp4'
                   for a in check.pages[12]['/Annots'])
    temporary.replace(path)
    print(f'Embedded {len(video):,} video bytes on slide 13. In-page playback configured.')


if __name__ == '__main__':
    main()
