import logging
import os.path
import shutil
import unicodedata

import configs
from configs import workspace_define
from utils import fs_util, glyph_util, unicode_util

logger = logging.getLogger('design-service')


def _parse_design_file_name(design_file_name):
    """
    解析设计文件名称
    例如：'0030 zh_cn,ja.png'
    """
    params = design_file_name.replace('.png', '').split(' ')
    assert 1 <= len(params) <= 2, design_file_name
    uni_hex_name = params[0].lower() if params[0] == 'notdef' else params[0].upper()
    if len(params) >= 2:
        available_locale_flavors = params[1].lower().split(',')
        for locale_flavor in available_locale_flavors:
            assert locale_flavor in configs.locale_flavors, design_file_name
    else:
        available_locale_flavors = []
    return uni_hex_name, available_locale_flavors


def classify_design_files(font_config):
    """
    按照 Unicode 区块分类设计文件
    """
    design_dir = os.path.join(workspace_define.design_dir, str(font_config.px))
    if os.path.isdir(design_dir):
        for design_flavor_name in os.listdir(design_dir):
            design_flavor_dir = os.path.join(design_dir, design_flavor_name)
            if os.path.isdir(design_flavor_dir):
                design_flavor_tmp_dir = os.path.join(design_dir, f'{design_flavor_name}.tmp')
                os.rename(design_flavor_dir, design_flavor_tmp_dir)
                os.mkdir(design_flavor_dir)
                for design_file_parent_dir, _, design_file_names in os.walk(design_flavor_tmp_dir):
                    for design_file_name in design_file_names:
                        if design_file_name.endswith('.png'):
                            design_file_from_path = os.path.join(design_file_parent_dir, design_file_name)
                            uni_hex_name, available_locale_flavors = _parse_design_file_name(design_file_name)
                            if uni_hex_name == 'notdef':
                                design_file_to_dir = design_flavor_dir
                            else:
                                code_point = int(uni_hex_name, 16)
                                _, unicode_block = unicode_util.index_block_by_code_point(configs.unicode_blocks, code_point)
                                block_dir_name = f'{unicode_block.begin:04X}-{unicode_block.end:04X} {unicode_block.name}'
                                design_file_to_dir = os.path.join(design_flavor_dir, block_dir_name)
                                if 0x4E00 <= code_point <= 0x9FFF:
                                    design_file_to_dir = os.path.join(design_file_to_dir, f'{uni_hex_name[0:-2]}-')
                            fs_util.make_dirs_if_not_exists(design_file_to_dir)
                            design_file_name = f'{uni_hex_name}{" " if len(available_locale_flavors) > 0 else ""}{",".join(available_locale_flavors)}.png'
                            design_file_to_path = os.path.join(design_file_to_dir, design_file_name)
                            shutil.move(design_file_from_path, design_file_to_path)
                            logger.info(f'classify design file: {design_file_to_path}')
                shutil.rmtree(design_flavor_tmp_dir)


def verify_design_files(font_config):
    """
    校验设计文件，并生成 SVG
    """
    design_dir = os.path.join(workspace_define.design_dir, str(font_config.px))
    svg_outputs_dir = os.path.join(workspace_define.svg_outputs_dir, str(font_config.px))
    for design_flavor_name in ['final', 'draft']:
        design_flavor_dir = os.path.join(design_dir, design_flavor_name)
        if os.path.isdir(design_flavor_dir):
            for design_file_parent_dir, _, design_file_names in os.walk(design_flavor_dir):
                svg_file_parent_dir = design_file_parent_dir.replace(design_dir, svg_outputs_dir)
                fs_util.make_dirs_if_not_exists(svg_file_parent_dir)
                for design_file_name in design_file_names:
                    if design_file_name.endswith('.png'):
                        design_file_path = os.path.join(design_file_parent_dir, design_file_name)
                        design_data, width, height = glyph_util.load_design_data_from_png(design_file_path)
                        uni_hex_name, _ = _parse_design_file_name(design_file_name)
                        if uni_hex_name == 'notdef':
                            code_point = -1
                            c = None
                        else:
                            code_point = int(uni_hex_name, 16)
                            c = chr(code_point)

                        # 校验设计文件的半角和全角尺寸
                        east_asian_width_status = unicodedata.east_asian_width(c) if c else 'N'
                        if east_asian_width_status == 'H' or east_asian_width_status == 'Na':
                            assert width * 2 == height, design_file_path
                        elif east_asian_width_status == 'F' or east_asian_width_status == 'W':
                            assert width == height, design_file_path
                        else:  # 'A' or 'N'
                            assert width * 2 == height or width == height, design_file_path
                        assert font_config.px == height, design_file_path

                        # 校验汉字顶部和右侧是否留有1像素间距
                        if 0x4E00 <= code_point <= 0x9FFF:
                            for alpha in design_data[0]:
                                assert alpha == 0, design_file_path
                            for i in range(0, len(design_data)):
                                assert design_data[i][-1] == 0, design_file_path

                        # 格式化设计文件
                        glyph_util.save_design_data_to_png(design_data, design_file_path)
                        logger.info(f'format design file: {design_file_path}')

                        # 生成 SVG
                        outlines = glyph_util.get_outlines_from_design_data(design_data, font_config.em_dot_size)
                        svg_file_path = os.path.join(svg_file_parent_dir, design_file_name.replace('.png', '.svg'))
                        glyph_util.save_outlines_to_svg(outlines, width * font_config.em_dot_size, height * font_config.em_dot_size, svg_file_path)
                        logger.info(f'make svg file: {svg_file_path}')


def collect_available_design(font_config):
    """
    收集可用字母表，生成设计文件映射表
    """
    # 遍历文件并分组
    alphabet = set()
    no_flavor_design_file_paths = {}
    locale_flavor_design_file_paths_map = {}
    for locale_flavor_config in font_config.locale_flavor_configs:
        locale_flavor_design_file_paths_map[locale_flavor_config.locale_flavor] = {}
    design_dir = os.path.join(workspace_define.design_dir, str(font_config.px))
    design_flavor_names = ['final']
    if configs.is_include_draft:
        design_flavor_names.append('draft')
    for design_flavor_name in design_flavor_names:
        design_flavor_dir = os.path.join(design_dir, design_flavor_name)
        if os.path.isdir(design_flavor_dir):
            for design_file_parent_dir, _, design_file_names in os.walk(design_flavor_dir):
                for design_file_name in design_file_names:
                    if design_file_name.endswith('.png'):
                        design_file_path = os.path.join(design_file_parent_dir, design_file_name)
                        uni_hex_name, available_locale_flavors = _parse_design_file_name(design_file_name)
                        if len(available_locale_flavors) > 0:
                            for locale_flavor_config in font_config.locale_flavor_configs:
                                if locale_flavor_config.locale_flavor in available_locale_flavors:
                                    locale_flavor_design_file_paths = locale_flavor_design_file_paths_map[locale_flavor_config.locale_flavor]
                                    if uni_hex_name == 'notdef':
                                        if '.notdef' not in locale_flavor_design_file_paths:
                                            locale_flavor_design_file_paths['.notdef'] = design_file_path
                                    else:
                                        code_point = int(uni_hex_name, 16)
                                        if code_point not in locale_flavor_design_file_paths:
                                            locale_flavor_design_file_paths[code_point] = design_file_path
                        else:
                            if uni_hex_name == 'notdef':
                                if '.notdef' not in no_flavor_design_file_paths:
                                    no_flavor_design_file_paths['.notdef'] = design_file_path
                            else:
                                code_point = int(uni_hex_name, 16)
                                if code_point not in no_flavor_design_file_paths:
                                    no_flavor_design_file_paths[code_point] = design_file_path
                                    alphabet.add(chr(code_point))
    # 字母表排序
    alphabet = list(alphabet)
    alphabet.sort(key=lambda c: ord(c))
    # 合并设计文件路径组
    design_file_paths_map = {}
    for locale_flavor, locale_flavor_design_file_paths in locale_flavor_design_file_paths_map.items():
        design_file_paths = dict(no_flavor_design_file_paths)
        design_file_paths.update(locale_flavor_design_file_paths)
        design_file_paths_map[locale_flavor] = design_file_paths
    return alphabet, design_file_paths_map
