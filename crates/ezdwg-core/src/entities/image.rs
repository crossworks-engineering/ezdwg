//! IMAGE (`AcDbRasterImage`, ODA 20.4.80): a class-based raster reference.
//!
//! WIPEOUT (`AcDbWipeout`) stores the same record. It has no image definition;
//! its clip boundary is the area it masks.
use crate::bit::{BitReader, Endian};
use crate::core::error::{DwgError, ErrorKind};
use crate::core::result::Result;
use crate::entities::common::{
    parse_common_entity_handles, parse_common_entity_header, parse_common_entity_header_r2007,
    parse_common_entity_header_r2010, parse_common_entity_header_r2013,
    parse_common_entity_layer_handle, read_handle_reference, CommonEntityHeader,
};

#[derive(Debug, Clone)]
pub struct ImageEntity {
    pub handle: u64,
    pub color_index: Option<u16>,
    pub true_color: Option<u32>,
    pub layer_handle: u64,
    pub class_version: u32,
    pub insert: (f64, f64, f64),
    pub u_vector: (f64, f64, f64),
    pub v_vector: (f64, f64, f64),
    pub size: (f64, f64),
    pub display_props: u16,
    pub clipping: bool,
    pub brightness: u8,
    pub contrast: u8,
    pub fade: u8,
    /// R2010+ only: 0 outside, 1 inside.
    pub clip_mode: Option<u8>,
    pub clip_type: u16,
    pub clip_vertices: Vec<(f64, f64)>,
    pub image_def_handle: u64,
    pub reactor_handle: u64,
}

pub fn decode_image(reader: &mut BitReader<'_>) -> Result<ImageEntity> {
    let header = parse_common_entity_header(reader)?;
    decode_image_with_header(reader, header, false, false, false)
}

pub fn decode_image_r2007(reader: &mut BitReader<'_>) -> Result<ImageEntity> {
    let header = parse_common_entity_header_r2007(reader)?;
    decode_image_with_header(reader, header, true, true, false)
}

pub fn decode_image_r2010(
    reader: &mut BitReader<'_>,
    object_data_end_bit: u32,
    object_handle: u64,
) -> Result<ImageEntity> {
    let mut header = parse_common_entity_header_r2010(reader, object_data_end_bit)?;
    header.handle = object_handle;
    decode_image_with_header(reader, header, true, true, true)
}

pub fn decode_image_r2013(
    reader: &mut BitReader<'_>,
    object_data_end_bit: u32,
    object_handle: u64,
) -> Result<ImageEntity> {
    let mut header = parse_common_entity_header_r2013(reader, object_data_end_bit)?;
    header.handle = object_handle;
    decode_image_with_header(reader, header, true, true, true)
}

/// Bytes of one clip boundary vertex: two raw doubles.
const CLIP_VERTEX_BYTES: u64 = 16;

fn decode_image_with_header(
    reader: &mut BitReader<'_>,
    header: CommonEntityHeader,
    allow_handle_decode_failure: bool,
    r2007_layer_only: bool,
    has_clip_mode: bool,
) -> Result<ImageEntity> {
    let class_version = reader.read_bl()?;
    let insert = reader.read_3bd()?;
    let u_vector = reader.read_3bd()?;
    let v_vector = reader.read_3bd()?;
    let size = (
        reader.read_rd(Endian::Little)?,
        reader.read_rd(Endian::Little)?,
    );
    let display_props = reader.read_bs()?;
    let clipping = reader.read_b()? != 0;
    let brightness = reader.read_rc()?;
    let contrast = reader.read_rc()?;
    let fade = reader.read_rc()?;
    let clip_mode = if has_clip_mode {
        Some(reader.read_b()?)
    } else {
        None
    };
    let clip_type = reader.read_bs()?;
    let count = if clip_type == 1 {
        2
    } else {
        let n = reader.read_bl()?;
        if n > 1_000_000 {
            return Err(DwgError::new(
                ErrorKind::Format,
                format!("IMAGE clip boundary vertex count is implausible: {n}"),
            ));
        }
        n as usize
    };
    // A vertex is two raw doubles. A count that the rest of the record cannot
    // hold fails here, before memory is reserved for it, with the error the
    // reads below would end in.
    let bytes_left = reader
        .total_bits()
        .saturating_sub(reader.tell_bits())
        .div_ceil(8);
    if (count as u64).saturating_mul(CLIP_VERTEX_BYTES) > bytes_left {
        return Err(
            DwgError::new(ErrorKind::Io, "unexpected EOF").with_offset(reader.tell_bits() / 8)
        );
    }
    let mut clip_vertices = Vec::with_capacity(count);
    for _ in 0..count {
        let x = reader.read_rd(Endian::Little)?;
        let y = reader.read_rd(Endian::Little)?;
        clip_vertices.push((x, y));
    }

    reader.set_bit_pos(header.obj_size);
    let handles_pos = reader.get_pos();
    let (layer_handle, image_def_handle, reactor_handle) = match (|| -> Result<_> {
        let layer = if r2007_layer_only {
            parse_common_entity_layer_handle(reader, &header)?
        } else {
            parse_common_entity_handles(reader, &header)?.layer
        };
        let def = read_handle_reference(reader, header.handle)?;
        let reactor = read_handle_reference(reader, header.handle)?;
        Ok((layer, def, reactor))
    })() {
        Ok(v) => v,
        Err(err)
            if allow_handle_decode_failure
                && matches!(
                    err.kind,
                    ErrorKind::Format | ErrorKind::Decode | ErrorKind::Io
                ) =>
        {
            reader.set_pos(handles_pos.0, handles_pos.1);
            let layer = parse_common_entity_layer_handle(reader, &header).unwrap_or(0);
            (layer, 0, 0)
        }
        Err(err) => return Err(err),
    };

    Ok(ImageEntity {
        handle: header.handle,
        color_index: header.color.index,
        true_color: header.color.true_color,
        layer_handle,
        class_version,
        insert,
        u_vector,
        v_vector,
        size,
        display_props,
        clipping,
        brightness,
        contrast,
        fade,
        clip_mode,
        clip_type,
        clip_vertices,
        image_def_handle,
        reactor_handle,
    })
}

#[cfg(test)]
mod tests {
    use super::{decode_image_r2013, ImageEntity};
    use crate::bit::{BitReader, BitWriter, Endian};
    use crate::core::error::ErrorKind;
    use crate::core::result::Result;

    /// An R2013 IMAGE or WIPEOUT record from its handle on, with a polygon
    /// clip boundary, and the bit where its handle stream begins. `count` is
    /// the vertex count the record states; `vertices` are the ones it holds.
    /// The handle stream is left empty: the reader takes its handles as
    /// optional.
    fn polygon_record(count: u32, vertices: &[(f64, f64)]) -> (Vec<u8>, u32) {
        let mut writer = BitWriter::new();
        writer.write_h(0, 0x50).expect("handle");
        writer.write_bs(0).expect("no extended data");
        writer.write_b(0).expect("no proxy graphic");
        writer.write_bb(0).expect("entity mode");
        writer.write_bl(0).expect("reactor count");
        writer.write_b(1).expect("no extension dictionary");
        writer.write_b(0).expect("no data store data");
        writer.write_b(1).expect("no links");
        writer.write_b(0).expect("color");
        writer.write_bd(1.0).expect("linetype scale");
        writer.write_bb(0).expect("linetype flags");
        writer.write_bb(0).expect("plot style flags");
        writer.write_bb(0).expect("material flags");
        writer.write_rc(0).expect("shadow flags");
        for _ in 0..3 {
            writer.write_b(0).expect("visual style flag");
        }
        writer.write_bs(0).expect("invisibility");
        writer.write_rc(0).expect("lineweight");

        writer.write_bl(0).expect("class version");
        writer.write_3bd(5.0, 6.0, 0.0).expect("insertion");
        writer.write_3bd(4.0, 0.0, 0.0).expect("u vector");
        writer.write_3bd(0.0, 2.0, 0.0).expect("v vector");
        writer.write_rd(Endian::Little, 1.0).expect("size x");
        writer.write_rd(Endian::Little, 1.0).expect("size y");
        writer.write_bs(7).expect("display properties");
        writer.write_b(1).expect("clipping");
        writer.write_rc(50).expect("brightness");
        writer.write_rc(50).expect("contrast");
        writer.write_rc(0).expect("fade");
        writer.write_b(0).expect("clip mode");
        writer.write_bs(2).expect("clip type: polygon");
        writer.write_bl(count).expect("vertex count");
        for (x, y) in vertices {
            writer.write_rd(Endian::Little, *x).expect("vertex x");
            writer.write_rd(Endian::Little, *y).expect("vertex y");
        }
        let data_end_bit = writer.tell_bits() as u32;
        (writer.into_bytes(), data_end_bit)
    }

    fn decode(record: &(Vec<u8>, u32)) -> Result<ImageEntity> {
        let mut reader = BitReader::new(&record.0);
        decode_image_r2013(&mut reader, record.1, 0x50)
    }

    const TRIANGLE: [(f64, f64); 3] = [(0.0, 0.0), (4.0, 0.0), (2.0, 3.0)];

    #[test]
    fn polygon_clip_boundary_is_read() {
        let entity = decode(&polygon_record(3, &TRIANGLE)).expect("decode");
        assert_eq!(entity.handle, 0x50);
        assert_eq!(entity.insert, (5.0, 6.0, 0.0));
        assert_eq!(entity.u_vector, (4.0, 0.0, 0.0));
        assert_eq!(entity.v_vector, (0.0, 2.0, 0.0));
        assert_eq!(entity.size, (1.0, 1.0));
        assert_eq!(entity.display_props, 7);
        assert!(entity.clipping);
        assert_eq!(entity.clip_mode, Some(0));
        assert_eq!(entity.clip_type, 2);
        assert_eq!(entity.clip_vertices, TRIANGLE.to_vec());
    }

    #[test]
    fn vertex_count_past_the_record_is_refused() {
        // The record states more vertices than it holds: from one more up to
        // the largest count the decoder takes at all.
        for count in [4, 1_000, 1_000_000] {
            let err = decode(&polygon_record(count, &TRIANGLE)).expect_err("count is too large");
            assert_eq!(err.kind, ErrorKind::Io, "count {count}");
        }
        let err = decode(&polygon_record(1_000_001, &TRIANGLE)).expect_err("implausible count");
        assert_eq!(err.kind, ErrorKind::Format);
        let err = decode(&polygon_record(u32::MAX, &TRIANGLE)).expect_err("implausible count");
        assert_eq!(err.kind, ErrorKind::Format);
    }

    #[test]
    fn empty_polygon_is_read_as_no_vertices() {
        let entity = decode(&polygon_record(0, &[])).expect("decode");
        assert!(entity.clip_vertices.is_empty());
    }
}
