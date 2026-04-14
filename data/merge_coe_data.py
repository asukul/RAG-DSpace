#!/usr/bin/env python3
"""Merge scraped CoE faculty data from ECpE, IMSE, and MSE into coe_faculty.json"""

import json
import re

# New faculty data from ECpE, IMSE, MSE scrape
new_faculty = [
  {"name": "Wang, Jie", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/jiew/", "photo_url": "https://www.engineering.iastate.edu/people/files/2025/07/JW_Headshot_JPEG-150x150.jpeg", "department": "Electrical and Computer Engineering"},
  {"name": "Tamrawi, Ahmed", "title": "Lecturer, Software Security", "profile_url": "https://www.engineering.iastate.edu/people/profile/atamrawi/", "photo_url": "https://www.engineering.iastate.edu/people/files/2024/11/IMG_1696-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Franklin, Jeff", "title": "Professor of Practice", "profile_url": "https://www.engineering.iastate.edu/people/profile/jeff7/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Ahmad, Arsalan", "title": "Research Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/aahmad/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Ahmed, Shakil", "title": "Assistant Professor, Term", "profile_url": "https://www.engineering.iastate.edu/people/profile/shakil/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Christy, Colin", "title": "Research Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/isucolin/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Li, Shuang", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/lishuang/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Farzana, Esmat", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/efarzana/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Cui, Bai", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/baicui/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Maharjan, Salish", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/salish/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Islam, Judith", "title": "Assistant Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/jislam/", "photo_url": "https://www.engineering.iastate.edu/people/files/2023/05/Judith-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Pramanik, Manojit", "title": "Associate Professor in Electrical and Computer Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/mano/", "photo_url": "https://www.engineering.iastate.edu/people/files/2024/02/9K3A6233-Edit_ls_v2-1-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Wang, Cheng", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/chengw/", "photo_url": "https://www.engineering.iastate.edu/people/files/2024/01/chengw_low-resolution_half_MB-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Babu, Sarath", "title": "Research Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/sarath4/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Shannon, Rachel Ann", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/rshannon/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Gaffar, Ashraf", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/gaffar/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Fila, Nicholas", "title": "Assistant Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/nfila/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Sarkar, Anwesha", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/anweshas/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Moothedath, Shana", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/mshana/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Gulmezoglu, Berk", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/bgulmez/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Villegas Pico, Hugo", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/hvillega/", "photo_url": "https://www.engineering.iastate.edu/people/files/2019/08/688-Villegas-Pico-Hugo-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Al Qaseer, Mohammad Tayeb", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/alqaseer-2/", "photo_url": "https://www.engineering.iastate.edu/people/files/2021/11/Mohammad-Tayeb-Al-Qaseer096-Selected-resized-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Ahamed, Md Maruf", "title": "Assistant Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/maruf/", "photo_url": "https://www.engineering.iastate.edu/people/files/2021/08/IMG_5207-Copy-1-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Selim, Mohamed", "title": "Associate Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/myoussef/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Zheng, Mai", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/mai/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Zhang, Hongwei", "title": "Richardson Professor of Electrical and Computer Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/hongwei/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Trajcevski, Goce", "title": "Kingland Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/gocet25/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Khokhar, Ashfaq", "title": "Professor & Palmer Department Chair", "profile_url": "https://www.engineering.iastate.edu/people/profile/ashfaq/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Huang, Cheng", "title": "Harpole-Pentair Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/chengh/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Duwe, Henry", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/duwe/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Kimber, Anne", "title": "EPRC Director and Research Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/akimber/", "photo_url": "https://www.engineering.iastate.edu/people/files/2018/09/Kimber20headshot-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Wang, Zhaoyu", "title": "Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/wzy/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/Zhaoyu-Wang-688-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Jahanbani Ardakani, Ali", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/alij/", "photo_url": "https://www.engineering.iastate.edu/people/files/2024/03/1347592-1.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Que, Long", "title": "Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/lque/", "photo_url": "https://www.engineering.iastate.edu/people/files/2023/01/Long-Que-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Dobson, Ian", "title": "Sandbulte Professor of Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/dobson/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Rursch, Julie", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/jrursch/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Jones, Phillip", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/phjones/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Bigelow, Timothy", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/bigelow/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Neihart, Nathan", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/neihart/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Zambreno, Joseph", "title": "Ross Martin Mehl and Marylyne Munas Mehl Computer Engineering Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/zambreno/", "photo_url": "https://www.engineering.iastate.edu/people/files/2024/03/9K3A6413-Edit-1-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Kim, Jaeyoun", "title": "Professor & Director of Graduate Education", "profile_url": "https://www.engineering.iastate.edu/people/profile/plasmon/", "photo_url": "https://www.engineering.iastate.edu/people/files/2023/01/KimJaeyounj06-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Ramamoorthy, Aditya", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/adityar/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/ece_Ramamoorthy_A_200808-150x150.png", "department": "Electrical and Computer Engineering"},
  {"name": "Pandey, Santosh", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/pandey/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Somani, Arun", "title": "Anson Marston Distinguished Professor, Phillip and Virginia Sproul Professor, Senior Associate Dean", "profile_url": "https://www.engineering.iastate.edu/people/profile/arun/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Rover, Diane", "title": "University Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/drover/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Stoytchev, Alexander", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/alexs/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "McCalley, James", "title": "Anson Marston Distinguished Professor and Jack London Chair in Power Systems Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/jdm/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Kim, Sang", "title": "Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/swkim/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Dalal, Vikram", "title": "Anson Marston Distinguished Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/vdalal/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Qiao, Daji", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/daji/", "photo_url": "https://www.engineering.iastate.edu/people/files/2020/03/daji3-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Vaswani, Namrata", "title": "Endowed Anderlik Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/namrata/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/VaswaniNamrata-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Ajjarapu, Venkataramana", "title": "Thomas M. Whitney Professor of Electrical Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/vajjarap/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/AjjarapuVenkataramana-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Kumar, Ratnesh", "title": "Barbara and James R. Palmer Professorship in Electrical and Computer Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/rkumar/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Guan, Yong", "title": "Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/guan/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Song, Jiming", "title": "Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/jisong/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Daniels, Thomas", "title": "Associate Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/daniels/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Dickerson, Julie", "title": "David C. Nicholas Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/julied/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Govindarasu, Manimaran", "title": "Anson Marston Distinguished Professor in Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/gmani/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Kothari, Suraj", "title": "Engineering Entrepreneurship Faculty Fellow in ECE", "profile_url": "https://www.engineering.iastate.edu/people/profile/kothari/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Dogandzic, Aleksandar", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/ald/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/DogandzicAleksandar-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Chen, Degang", "title": "Jerry R. Junkins Chair in Electrical and Computer Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/djchen/", "photo_url": "https://www.engineering.iastate.edu/people/files/2018/09/ece_Chen_D_200808-150x150.png", "department": "Electrical and Computer Engineering"},
  {"name": "Geiger, Randall", "title": "Tunc and Lale Doluca Professor in Electrical and Computer Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/rlgeiger/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/GeigerRandall-150x150.jpg", "department": "Electrical and Computer Engineering"},
  {"name": "Tyagi, Akhilesh", "title": "Professor and Director of Software Engineering Program", "profile_url": "https://www.engineering.iastate.edu/people/profile/tyagi/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Mina, Mani", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/mmina/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  {"name": "Jacobson, Doug", "title": "University Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/dougj/", "photo_url": None, "department": "Electrical and Computer Engineering"},
  # IMSE
  {"name": "Anderson, Justin", "title": "Assistant Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/jander03/", "photo_url": "https://www.engineering.iastate.edu/people/files/2025/10/Justin-Anderson-688-150x150.jpg", "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Jose, Esther", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/estherjo/", "photo_url": "https://www.engineering.iastate.edu/people/files/2025/08/Esther-Jose-688-4-150x150.jpg", "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Wei, Guanzhou", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/gwei/", "photo_url": "https://www.engineering.iastate.edu/people/files/2025/06/Guanzhou-Wei-688-150x150.jpg", "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Miller, Tim", "title": "Professor of Practice", "profile_url": "https://www.engineering.iastate.edu/people/profile/mfg4engr/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Stallard, Michelle", "title": "Assistant Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/mstalla/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Liu, Jundi", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/jundiliu/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Li, Bin", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/binl/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Hamilton, Jakob", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/jdham/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Liao, Yiliang", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/leonl/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Bruner, Aaron", "title": "Professor of Practice", "profile_url": "https://www.engineering.iastate.edu/people/profile/aaron-bruner/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Li, Qing", "title": "Building a World of Difference Faculty Fellow in Engineering, Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/qlijane/", "photo_url": "https://www.engineering.iastate.edu/people/files/2018/08/Li-Qing-Portrait-CROP-200x270-1-150x150.jpg", "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "De Brabanter, Kris", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/kbrabant/", "photo_url": "https://www.engineering.iastate.edu/people/files/2018/07/Kris-De-Brabanter-portrait-688-150x150.jpg", "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Hammond, David", "title": "Assistant Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/dhammond/", "photo_url": "https://www.engineering.iastate.edu/people/files/2018/07/David-Hammond-688-150x150.jpg", "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "MacKenzie, Cameron", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/camacken/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Dorneich, Michael", "title": "Morrill Professor, Joseph Walkup Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/dorneich/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Stone, Richard", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/rstone/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Mirka, Gary", "title": "University Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/mirka/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Peters, Frank", "title": "C. G. Turk and Joyce A. Therkildsen Professor, Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/fpeters/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Olafsson, Sigurdur", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/olafsson/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Sly, David", "title": "Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/davesly/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Min, Kyung", "title": "Associate Professor Emeritus", "profile_url": "https://www.engineering.iastate.edu/people/profile/jomin/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/Min-F11-small-150x150.jpg", "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Potter, Leslie", "title": "College of Engineering Distinguished Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/potter/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/Leslie-Potter-688-150x150.jpg", "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Frank, Matthew", "title": "C.G. Turk and Joyce A. Therkildsen Department Chair", "profile_url": "https://www.engineering.iastate.edu/people/profile/mfrank/", "photo_url": "https://www.engineering.iastate.edu/people/files/2024/04/2024-Headshot_directory-sized-150x150.jpg", "department": "Industrial and Manufacturing Systems Engineering"},
  {"name": "Gilbert, Stephen", "title": "Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/gilbert/", "photo_url": None, "department": "Industrial and Manufacturing Systems Engineering"},
  # MSE
  {"name": "Du, Yang", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/yangdu/", "photo_url": "https://www.engineering.iastate.edu/people/files/2024/09/Yang-Du-150x150.jpg", "department": "Materials Science and Engineering"},
  {"name": "Johnson, Patrick", "title": "Professor and Associate Chair for Graduate Education and Research", "profile_url": "https://www.engineering.iastate.edu/people/profile/paj3/", "photo_url": "https://www.engineering.iastate.edu/people/files/2023/08/Johnson-Patrick-1-150x150.jpg", "department": "Materials Science and Engineering"},
  {"name": "Faierson, Eric", "title": "Research Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/faierson/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Kirillova, Alina", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/alinakir/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "An, Qi", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/qan/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Chang, Boyce", "title": "Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/boyce/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Cornelius, Chris", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/cjcornel/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Vachhani, Shraddha", "title": "Adjunct Assistant Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/vachhani/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Pathak, Sid", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/pathak/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Eisenmann, David", "title": "Associate Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/djeisen/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Jiang, Shan", "title": "Associate Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/sjiang1/", "photo_url": "https://www.engineering.iastate.edu/people/files/2017/10/Jiang-Shan-1-150x150.jpg", "department": "Materials Science and Engineering"},
  {"name": "Johnson, Duane", "title": "Anson Marston Distinguished Professor of Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/ddj/", "photo_url": "https://www.engineering.iastate.edu/people/files/2024/10/Duane-Johnson_Small-150x150.jpeg", "department": "Materials Science and Engineering"},
  {"name": "Cui, Jun", "title": "Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/cuijun/", "photo_url": "https://www.engineering.iastate.edu/people/files/2025/12/Jun-150x150.jpg", "department": "Materials Science and Engineering"},
  {"name": "Collins, Peter", "title": "Stanley Chair (Professorship) in Interdisciplinary Engineering", "profile_url": "https://www.engineering.iastate.edu/people/profile/pcollins/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/Collins-Pete-2-150x150.jpg", "department": "Materials Science and Engineering"},
  {"name": "Martin, Steve", "title": "Distinguished Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/swmartin/", "photo_url": "https://www.engineering.iastate.edu/people/files/2016/01/Martin-Steve-150x150.jpg", "department": "Materials Science and Engineering"},
  {"name": "Constant, Alan", "title": "Teaching Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/alcon/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Constant, Kristen", "title": "", "profile_url": "https://www.engineering.iastate.edu/people/profile/constant/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Napolitano, Ralph", "title": "Professor, Associate Chair", "profile_url": "https://www.engineering.iastate.edu/people/profile/ren1/", "photo_url": None, "department": "Materials Science and Engineering"},
  {"name": "Tan, Xiaoli", "title": "Professor", "profile_url": "https://www.engineering.iastate.edu/people/profile/xtan/", "photo_url": None, "department": "Materials Science and Engineering"},
]

def generate_id(name):
    """Generate ID from name like 'Last, First' -> 'last-first'"""
    name_clean = re.sub(r'[^\w\s,-]', '', name.lower())
    parts = name_clean.split(',')
    if len(parts) >= 2:
        last = parts[0].strip().replace(' ', '-')
        first = parts[1].strip().split()[0] if parts[1].strip() else ''
        return f"{last}-{first}" if first else last
    return name_clean.replace(' ', '-')

# Load existing data
with open('coe_faculty.json', 'r') as f:
    existing = json.load(f)

print(f"Existing faculty count: {len(existing)}")

# Track existing profile URLs to avoid duplicates
existing_urls = {f['profile_url'] for f in existing}

# Add new faculty with proper formatting
added = 0
for fac in new_faculty:
    if fac['profile_url'] not in existing_urls:
        fac['college'] = 'College of Engineering'
        fac['id'] = generate_id(fac['name'])
        fac['email'] = None  # Will need to be fetched later
        existing.append(fac)
        existing_urls.add(fac['profile_url'])
        added += 1

print(f"Added {added} new faculty")
print(f"Total faculty count: {len(existing)}")

# Save updated data
with open('coe_faculty.json', 'w') as f:
    json.dump(existing, f, indent=2)

print("Updated coe_faculty.json")
